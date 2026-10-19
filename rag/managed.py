"""Tenant-scoped retrieval from durable uploaded collections.

BM25 is always available. Optional stored embeddings add dense retrieval and RRF.
The source of truth is SQL, so activation/deletion and restarts cannot diverge
from a process-local pickle. Legacy Pinecone is used only for unmanaged fixtures.
"""
from __future__ import annotations

import math
import re
from typing import Any

from langchain_core.documents import Document
from sqlalchemy import select

from db.models import KnowledgeContentRow, KnowledgeSnapshotRow
from db.session import SessionLocal
from rag.hybrid import BM25Index, reciprocal_rank_fusion

_STOP = set("a an the is are what how can i my me for of to and in on do does your you it please policy policies".split())


def terms(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", text.lower()) if word not in _STOP and len(word) > 2}


class TenantRetriever:
    def __init__(self) -> None:
        self._legacy = None

    def retrieve(self, query: str, k: int = 8, final_k: int = 4,
                 metadata_filter: dict | None = None, **kwargs: Any) -> list[Document]:
        tenant = str((metadata_filter or {}).get("tenant_id") or "")
        if not tenant:
            return []
        with SessionLocal() as db:
            managed = db.execute(select(KnowledgeSnapshotRow.id).where(
                KnowledgeSnapshotRow.tenant_id == tenant).limit(1)).scalar_one_or_none()
            rows = db.execute(select(KnowledgeContentRow).join(
                KnowledgeSnapshotRow, KnowledgeSnapshotRow.id == KnowledgeContentRow.id).where(
                KnowledgeContentRow.tenant_id == tenant,
                KnowledgeSnapshotRow.tenant_id == tenant,
                KnowledgeSnapshotRow.status == "ingested")).scalars().all()
            chunks = [dict(chunk) for row in rows for chunk in row.chunks_json]
        if managed is None:
            # Legacy reference data is opt-in and never used for newly signed-up brands.
            from config.tenant_contract import platform_tenant_yaml_path
            import os
            if not platform_tenant_yaml_path(tenant).is_file() or not os.getenv("PINECONE_API_KEY"):
                return []
            if self._legacy is None:
                from rag.retrieval import AdvancedRAGRetriever
                self._legacy = AdvancedRAGRetriever()
            return self._legacy.retrieve(query, k=k, final_k=final_k, metadata_filter=metadata_filter, **kwargs)
        docs = []
        vector_by_id = {}
        query_terms = terms(query)
        for chunk in chunks:
            metadata = dict(chunk["metadata"])
            if metadata.get("tenant_id") != tenant:
                continue
            text = chunk["page_content"]
            if not query_terms.intersection(terms(text)):
                continue
            metadata["citation"] = f"{metadata.get('source', 'Policy')}, Page {metadata.get('page', '')}, Clause {metadata.get('clause') or metadata.get('chunk_id')}"
            metadata["managed"] = True
            doc = Document(page_content=text, metadata=metadata)
            docs.append(doc)
            if chunk.get("embedding"):
                vector_by_id[metadata["chunk_id"]] = chunk["embedding"]
        if not docs:
            return []
        sparse = BM25Index(docs).search(query, k=max(k, final_k * 3))
        if vector_by_id:
            from langchain_openai import OpenAIEmbeddings
            query_vector = OpenAIEmbeddings(model="text-embedding-3-small", request_timeout=15, max_retries=1).embed_query(query)
            def cosine(doc: Document) -> float:
                vector = vector_by_id.get(doc.metadata["chunk_id"], [])
                denom = math.sqrt(sum(x*x for x in vector) * sum(x*x for x in query_vector))
                return sum(a*b for a, b in zip(vector, query_vector)) / denom if denom else 0.0
            dense = sorted([(doc, cosine(doc)) for doc in docs], key=lambda pair: pair[1], reverse=True)
            return reciprocal_rank_fusion(dense[:k], sparse, k=final_k)
        return [doc for doc, _ in sparse[:final_k]]
