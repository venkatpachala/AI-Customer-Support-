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


def normalize_chunks(chunks: List[Document]) -> List[Document]:
    """
    Enforce canonical source identity + stable chunk_id + Pinecone-safe metadata.
    """
    normalized: List[Document] = []

    for i, doc in enumerate(chunks):
        md = dict(doc.metadata or {})

        page = md.get("page", md.get("page_number", ""))
        clause = md.get("clause", "") or ""
        section = md.get("section", "") or ""

        # Prefer existing clause-aware id if present; otherwise build stable id
        chunk_id = md.get("chunk_id") or f"{SOURCE_ID}:p{page}:{clause or 'noclause'}:c{i}"

        new_md = {
            "source_id": SOURCE_ID,
            "source": SOURCE_NAME,
            "page": page if page is not None else "",
            "clause": clause,
            "section": section,
            "chunk_id": chunk_id,
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


def save_bm25_corpus(chunks: List[Document]) -> None:
    BM25_CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(BM25_CORPUS_PATH, "wb") as f:
        pickle.dump(chunks, f)
    print(f"Saved BM25 corpus: {BM25_CORPUS_PATH} ({len(chunks)} chunks)")


def ingest_zepto_policy() -> None:
    if not PDF_PATH.exists():
        raise FileNotFoundError(f"Policy PDF not found: {PDF_PATH.resolve()}")

    print(f"Loading single canonical PDF: {PDF_PATH}")
    loader = PyPDFLoader(str(PDF_PATH))
    pages = loader.load()
    print(f"Loaded {len(pages)} pages")

    # Production chunker (clause/section aware)
    raw_chunks = create_policy_chunks(pages)
    print(f"Created {len(raw_chunks)} policy chunks")

    chunks = normalize_chunks(raw_chunks)
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
    save_bm25_corpus(chunks)

    print("Ingestion complete")
    print(f"  source_id = {SOURCE_ID}")
    print(f"  source    = {SOURCE_NAME}")
    print(f"  chunks    = {len(chunks)}")
    print(f"  bm25      = {BM25_CORPUS_PATH}")


if __name__ == "__main__":
    ingest_zepto_policy()