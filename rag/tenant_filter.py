"""Tenant scope for retrieval. A missing filter must not borrow another brand's chunks."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from langchain_core.documents import Document


def pinecone_tenant_filter(tenant_id: str) -> Dict[str, str]:
    tenant = str(tenant_id or "").strip()
    return {"tenant_id": tenant}


def is_duplicate_source(source: Any) -> bool:
    """Windows paths and a second PDF filename are not the canonical tenant source."""
    text = str(source or "").strip()
    if not text:
        return False
    if "\\" in text or re.match(r"^[A-Za-z]:", text):
        return True
    lowered = text.lower().replace(" ", "_")
    if lowered.endswith(".pdf"):
        return True
    return False


def dedup_key(source_id: Any, clause: Any, prefix: Any) -> str:
    return f"{source_id}|{str(clause or '').strip()}|{str(prefix or '')[:160]}"


def belongs_to_tenant(metadata: Optional[Dict[str, Any]], tenant_id: str) -> bool:
    return str((metadata or {}).get("tenant_id") or "") == str(tenant_id or "").strip()


def select_tenant_docs(docs: Iterable[Document], tenant_id: str) -> List[Document]:
    """Keep one tenant. Drop path copies. Never fill the gap from another tenant."""
    kept: List[Document] = []
    for doc in docs:
        metadata = dict(doc.metadata or {})
        if is_duplicate_source(metadata.get("source")):
            continue
        if not belongs_to_tenant(metadata, tenant_id):
            continue
        kept.append(doc)
    return kept
