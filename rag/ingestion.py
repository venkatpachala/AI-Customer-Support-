import os
import pickle
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document

from rag.chunking import create_policy_chunks
from rag.retrieval import AdvancedRAGRetriever

load_dotenv()

# Canonical single source
PDF_PATH = Path("attachments/Zepto Terms of Use.pdf")
BM25_CORPUS_PATH = Path("rag/bm25_corpus.pkl")

SOURCE_ID = "zepto_terms_v1"
SOURCE_NAME = "Zepto Terms of Use"


def sanitize_metadata(metadata: dict) -> dict:
    """
    Pinecone only accepts:
    string, number, boolean, or list of strings.
    Never allow None.
    """
    clean = {}
    for key, value in metadata.items():
        if value is None:
            clean[key] = ""
        elif isinstance(value, (str, int, float, bool)):
            clean[key] = value
        elif isinstance(value, list):
            clean[key] = [str(v) for v in value if v is not None]
        else:
            clean[key] = str(value)
    return clean


def tenant_knowledge_dir(tenant_id: str) -> Path:
    return Path("tenants") / tenant_id / "knowledge"


def tenant_pdf(tenant_id: str) -> Path:
    folder = tenant_knowledge_dir(tenant_id)
    pdfs = sorted(folder.glob("*.pdf")) if folder.is_dir() else []
    if not pdfs:
        raise FileNotFoundError(f"No canonical PDF in {folder}")
    return pdfs[0]


def bm25_corpus_path(tenant_id: str) -> Path:
    return Path(f"rag/bm25_corpus_{tenant_id}.pkl")


def normalize_chunks(
    chunks: List[Document],
    *,
    tenant_id: str = "zepto",
    source_id: str = SOURCE_ID,
    source_name: str = SOURCE_NAME,
    knowledge_snapshot: str = "unversioned",
) -> List[Document]:
    """
    Enforce canonical source identity + stable chunk_id + Pinecone-safe metadata.
    """
    normalized: List[Document] = []

    for i, doc in enumerate(chunks):
        md = dict(doc.metadata or {})

        page = md.get("page", md.get("page_number", ""))
        clause = md.get("clause", "") or ""
        section = md.get("section", "") or ""
        chunk_id = f"{source_id}:c{i}"

        new_md = {
            "tenant_id": tenant_id,
            "source_id": source_id,
            "source": source_name,
            "page": page if page is not None else "",
            "clause": clause,
            "section": section,
            "chunk_id": chunk_id,
            "knowledge_snapshot": knowledge_snapshot,
            "chunk_index": i,
        }

        # keep any extra useful metadata, but overwrite identity fields
        for k, v in md.items():
            if k not in new_md:
                new_md[k] = v

        normalized.append(
            Document(
                page_content=(doc.page_content or "").strip(),
                metadata=sanitize_metadata(new_md),
            )
        )

    # drop empty chunks
    normalized = [d for d in normalized if d.page_content]
    return normalized


def save_bm25_corpus(chunks: List[Document], tenant_id: str = "zepto") -> None:
    path = bm25_corpus_path(tenant_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(chunks, f)
    print(f"Saved BM25 corpus: {path} ({len(chunks)} chunks)")


def ingest_zepto_policy() -> None:
    from config.tenant_contract import load_platform_tenant

    pdf_path = tenant_pdf("zepto")
    snapshot = load_platform_tenant("zepto").versions.knowledge_snapshot or "unversioned"
    print(f"Loading single canonical PDF: {pdf_path}")
    loader = PyPDFLoader(str(pdf_path))
    pages = loader.load()
    print(f"Loaded {len(pages)} pages")

    # Production chunker (clause/section aware)
    raw_chunks = create_policy_chunks(pages)
    print(f"Created {len(raw_chunks)} policy chunks")

    chunks = normalize_chunks(raw_chunks, tenant_id="zepto", knowledge_snapshot=snapshot)
    print(f"Normalized {len(chunks)} chunks with canonical metadata")

    # Diagnostics
    with_clause = sum(1 for c in chunks if c.metadata.get("clause"))
    print(f"Chunks with clause metadata: {with_clause}/{len(chunks)}")
    for c in chunks[:5]:
        preview = c.page_content[:90].replace("\n", " ")
        print(f"  - {c.metadata.get('chunk_id')} | {preview}")

    # Upsert to vector DB
    print("Upserting chunks to Pinecone...")
    retriever = AdvancedRAGRetriever()
    retriever.add_documents(chunks)
    print(f"Pinecone upsert complete: {len(chunks)} chunks")

    # Save exact same chunks for BM25/hybrid
    save_bm25_corpus(chunks, "zepto")

    print("Ingestion complete")
    print(f"  source_id = {SOURCE_ID}")
    print(f"  source    = {SOURCE_NAME}")
    print(f"  chunks    = {len(chunks)}")
    print(f"  bm25      = {BM25_CORPUS_PATH}")


if __name__ == "__main__":
    ingest_zepto_policy()