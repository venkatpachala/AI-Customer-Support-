import os
import pickle
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from rag.chunking import create_policy_chunks
from rag.retrieval import AdvancedRAGRetriever
from dotenv import load_dotenv

load_dotenv()

# Update this path if needed
PDF_PATH = r"D:\D2C\attachments\Zepto Terms of Use.pdf"
BM25_CORPUS_PATH = Path("rag/bm25_corpus.pkl")


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
            clean[key] = [str(v) for v in value]
        else:
            clean[key] = str(value)
    return clean


def ingest_zepto_policy():
    if not os.path.exists(PDF_PATH):
        print(f"PDF not found at: {PDF_PATH}")
        return

    print("Loading Zepto Terms of Use...")
    loader = PyPDFLoader(PDF_PATH)
    pages = loader.load()
    print(f"Loaded {len(pages)} pages")

    # Structure-aware chunking
    chunks = create_policy_chunks(pages)
    print(f"Created {len(chunks)} optimized chunks")

    # Final safety sanitize for Pinecone
    for chunk in chunks:
        chunk.metadata = sanitize_metadata(chunk.metadata)

    # 1. Ingest into Pinecone
    retriever = AdvancedRAGRetriever()
    retriever.vectorstore.add_documents(chunks)
    print(f"Successfully ingested {len(chunks)} chunks into Pinecone")

    # 2. Save local corpus for BM25 / hybrid search
    BM25_CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(BM25_CORPUS_PATH, "wb") as f:
        pickle.dump(chunks, f)

    print(f"Saved BM25 corpus to {BM25_CORPUS_PATH}")
    print("Ingestion complete.")


if __name__ == "__main__":
    ingest_zepto_policy()