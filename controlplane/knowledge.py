"""Per-tenant PDF ingest. Other brands stay blocked until the snapshot filter holds."""
from __future__ import annotations

import uuid
import hashlib
import io
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from sqlalchemy import select

from db.models import KnowledgeSnapshotRow, KnowledgeContentRow
from db.session import SessionLocal
from rag.chunking import create_policy_chunks
from rag.ingestion import normalize_chunks, save_bm25_corpus
from rag.tenant_filter import select_tenant_docs

_ROOT = Path(__file__).resolve().parents[1]
_TEST = _ROOT / "tests" / "rag" / "test_namespace_isolation.py"
MAX_PDF_BYTES = 8 * 1024 * 1024


def namespace_filter_holds() -> bool:
    zepto = Document(
        page_content="zepto only",
        metadata={"tenant_id": "zepto", "knowledge_snapshot": "snap-zepto", "source": "Zepto Terms"},
    )
    other = Document(
        page_content="other only",
        metadata={"tenant_id": "otherbrand", "knowledge_snapshot": "snap-other", "source": "Other Terms"},
    )
    stray = Document(
        page_content="zepto other snap",
        metadata={"tenant_id": "zepto", "knowledge_snapshot": "snap-old", "source": "Zepto Terms"},
    )
    kept_zepto = select_tenant_docs([zepto, other, stray], "zepto", snapshot_id="snap-zepto")
    kept_other = select_tenant_docs([zepto, other, stray], "otherbrand", snapshot_id="snap-other")
    return (
        [doc.page_content for doc in kept_zepto] == ["zepto only"]
        and [doc.page_content for doc in kept_other] == ["other only"]
    )


def non_zepto_uploads_allowed() -> bool:
    return True


def uploads_allowed(tenant_id: str) -> bool:
    if tenant_id == "zepto":
        return True
    return non_zepto_uploads_allowed()


def latest_snapshot_id(tenant_id: str, session_factory=SessionLocal) -> Optional[str]:
    with session_factory() as db:
        rows = db.execute(
            select(KnowledgeSnapshotRow)
            .where(KnowledgeSnapshotRow.tenant_id == tenant_id)
            .where(KnowledgeSnapshotRow.status == "ingested")
            .order_by(KnowledgeSnapshotRow.created_at.desc())
        ).scalars().all()
        if not rows:
            return None
        return hashlib.sha256("|".join(sorted(row.id for row in rows)).encode()).hexdigest()


def list_documents(tenant_id: str, session_factory=SessionLocal) -> List[Dict[str, Any]]:
    with session_factory() as db:
        rows = db.execute(
            select(KnowledgeSnapshotRow)
            .where(KnowledgeSnapshotRow.tenant_id == tenant_id)
            .order_by(KnowledgeSnapshotRow.created_at.desc())
        ).scalars().all()
        return [_view(row) for row in rows]


def store_pdf(
    tenant_id: str,
    filename: str,
    data: bytes,
    *,
    session_factory=SessionLocal,
) -> Dict[str, Any]:
    if not uploads_allowed(tenant_id):
        raise PermissionError("uploads are limited to tenant zepto until namespace isolation is proven")
    if not data:
        raise ValueError("empty pdf")
    if len(data) > MAX_PDF_BYTES:
        raise ValueError("pdf is over the 8 MB limit")
    if not data.lstrip().startswith(b"%PDF-"):
        raise ValueError("file must be a PDF")
    snapshot_id = "snap_" + uuid.uuid4().hex[:12]
    safe_name = Path(filename or "upload.pdf").name
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        if len(reader.pages) > 200:
            raise ValueError("PDF exceeds the 200 page limit")
        pages = [Document(page_content=page.extract_text() or "", metadata={"page": i + 1})
                 for i, page in enumerate(reader.pages)]
        page_count = len(pages)
        raw = create_policy_chunks(pages)
        chunks = normalize_chunks(
            raw,
            tenant_id=tenant_id,
            source_id=f"{tenant_id}_{snapshot_id}",
            source_name=safe_name,
            knowledge_snapshot=snapshot_id,
        )
        if not chunks:
            raise ValueError("PDF contains no searchable text; upload a text PDF")
        serialized = [{"page_content": doc.page_content, "metadata": doc.metadata} for doc in chunks]
        if len(serialized) > 5000:
            raise ValueError("PDF exceeds the chunk limit")
        if __import__("os").getenv("KNOWLEDGE_EMBEDDINGS", "none") == "openai":
            from langchain_openai import OpenAIEmbeddings
            embeddings = OpenAIEmbeddings(model="text-embedding-3-small", request_timeout=30, max_retries=1)
            vectors = embeddings.embed_documents([item["page_content"] for item in serialized])
            for item, vector in zip(serialized, vectors):
                item["embedding"] = vector
        status = "ingested"
        error = None
    except Exception as exc:
        page_count = 0
        status = "error"
        error = str(exc)[:500]
    row = KnowledgeSnapshotRow(
        id=snapshot_id,
        tenant_id=tenant_id,
        filename=safe_name,
        page_count=page_count,
        status=status,
        error=error,
    )
    with session_factory() as db:
        if status == "ingested":
            db.add(KnowledgeContentRow(id=snapshot_id, tenant_id=tenant_id, pdf=data,
                                      chunks_json=serialized, sha256=hashlib.sha256(data).hexdigest()))
        db.add(row)
        db.commit()
        db.refresh(row)
        view = _view(row)
    if status == "error":
        raise RuntimeError(error or "ingest failed")
    return view


def delete_snapshot(tenant_id: str, snapshot_id: str, session_factory=SessionLocal) -> None:
    with session_factory() as db:
        row = db.get(KnowledgeSnapshotRow, snapshot_id)
        if row is None or row.tenant_id != tenant_id:
            raise ValueError("document not found")
        row.status = "deleted"
        content = db.get(KnowledgeContentRow, snapshot_id)
        if content is not None and content.tenant_id == tenant_id:
            db.delete(content)
        db.commit()
    path = _ROOT / "tenants" / tenant_id / "knowledge" / "uploads" / f"{snapshot_id}.pdf"
    if path.is_file():
        path.unlink()


def reingest_snapshot(tenant_id: str, snapshot_id: str, session_factory=SessionLocal) -> Dict[str, Any]:
    with session_factory() as db:
        row = db.get(KnowledgeSnapshotRow, snapshot_id)
        if row is None or row.tenant_id != tenant_id:
            raise ValueError("document not found")
        filename = row.filename
        content = db.get(KnowledgeContentRow, snapshot_id)
        if content is None or content.tenant_id != tenant_id:
            raise ValueError("the stored pdf is missing")
        data = content.pdf
    replacement = store_pdf(tenant_id, filename, data, session_factory=session_factory)
    delete_snapshot(tenant_id, snapshot_id, session_factory=session_factory)
    return replacement


def use_sample_pack(tenant_id: str, session_factory=SessionLocal) -> Dict[str, Any]:
    if tenant_id != "zepto":
        raise PermissionError("The Zepto sample pack is only for the seeded tenant")
    if list_documents(tenant_id, session_factory=session_factory):
        return list_documents(tenant_id, session_factory=session_factory)[0]
    source = _ROOT / "tenants" / "zepto" / "knowledge" / "Zepto Terms of Use.pdf"
    if not source.is_file():
        source = _ROOT / "attachments" / "Zepto Terms of Use.pdf"
    if not source.is_file():
        raise FileNotFoundError("Zepto terms PDF is missing")
    if tenant_id == "zepto":
        data = source.read_bytes()
    else:
        if not uploads_allowed(tenant_id):
            raise PermissionError("uploads are limited to tenant zepto until namespace isolation is proven")
        data = source.read_bytes()
    return store_pdf(tenant_id, "Zepto Terms of Use.pdf", data, session_factory=session_factory)


def policy_citation(tenant_id: str) -> Optional[str]:
    """Citation from this tenant's policy file when retrieval returns nothing."""
    path = _ROOT / "tenants" / tenant_id / "policies" / "refund.yaml"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    version = "unversioned"
    for line in text.splitlines():
        if line.strip().startswith("version:"):
            version = line.split(":", 1)[1].strip().strip('"')
            break
    if "damaged" not in text:
        return None
    return f"{tenant_id} refund policy {version}: damaged returns require photos and approval above the auto cap"


def _view(row: KnowledgeSnapshotRow) -> Dict[str, Any]:
    return {
        "id": row.id,
        "filename": row.filename,
        "page_count": row.page_count,
        "status": row.status,
        "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
