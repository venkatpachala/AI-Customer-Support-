import os
from langchain_community.document_loaders import PyPDFLoader
from rag.chunking import create_policy_chunks
from rag.retrieval import AdvancedRAGRetriever
from dotenv import load_dotenv

load_dotenv()

PDF_PATH = r"D:\D2C\attachments\Zepto Terms of Use.pdf"  # Update if needed

def ingest_zepto_policy(clear_existing: bool = False):
    if not os.path.exists(PDF_PATH):
        print(f"PDF not found at: {PDF_PATH}")
        return

    print("Loading Zepto Terms of Use...")
    loader = PyPDFLoader(PDF_PATH)
    pages = loader.load()
    print(f"Loaded {len(pages)} pages")

    # Better chunking
    chunks = create_policy_chunks(pages)
    print(f"Created {len(chunks)} optimized chunks")

    retriever = AdvancedRAGRetriever()

    if clear_existing:
        # Optional: clear previous vectors if needed
        print("Note: Clearing is not implemented here. Create a new index if required.")

    retriever.vectorstore.add_documents(chunks)
    print(f"Successfully ingested {len(chunks)} chunks into Pinecone")

if __name__ == "__main__":
    ingest_zepto_policy()