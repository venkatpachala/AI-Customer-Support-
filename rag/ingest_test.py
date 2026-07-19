# rag/ingest_test.py
from langchain_core.documents import Document
from rag.retrieval import AdvancedRAGRetriever

retriever = AdvancedRAGRetriever()

docs = [
    Document(
        page_content="Our return policy allows damaged products to be returned within 30 days for full refund or replacement. Provide order ID and photos.",
        metadata={"source": "returns_policy.pdf", "category": "returns"}
    )
]

retriever.vectorstore.add_documents(docs)
print("✅ Ingested!")