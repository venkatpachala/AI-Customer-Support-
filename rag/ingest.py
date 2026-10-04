"""Ingest one tenant's canonical PDF. python -m rag.ingest --tenant zepto"""
from __future__ import annotations

import argparse

from config.tenant_contract import load_platform_tenant
from langchain_community.document_loaders import PyPDFLoader

from rag.chunking import create_policy_chunks
from rag.ingestion import normalize_chunks, save_bm25_corpus, tenant_pdf


def ingest_tenant(tenant_id: str) -> int:
    tenant = load_platform_tenant(tenant_id)
    snapshot = tenant.versions.knowledge_snapshot or "unversioned"
    pdf_path = tenant_pdf(tenant_id)
    pages = PyPDFLoader(str(pdf_path)).load()
    raw = create_policy_chunks(pages)
    source_id = f"{tenant_id}_terms_v1"
    chunks = normalize_chunks(
        raw,
        tenant_id=tenant_id,
        source_id=source_id,
        source_name=tenant.brand or tenant_id,
        knowledge_snapshot=snapshot,
    )
    save_bm25_corpus(chunks, tenant_id)
    _upsert_pinecone(chunks)
    print(f"ingested {tenant_id} chunks={len(chunks)} snapshot={snapshot}")
    return len(chunks)


def _upsert_pinecone(chunks) -> None:
    import os

    if not os.getenv("PINECONE_API_KEY", "").strip():
        print("pinecone skipped: PINECONE_API_KEY is unset")
        return
    from rag.retrieval import AdvancedRAGRetriever

    AdvancedRAGRetriever().add_documents(chunks)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True)
    args = parser.parse_args()
    ingest_tenant(args.tenant)


if __name__ == "__main__":
    main()
