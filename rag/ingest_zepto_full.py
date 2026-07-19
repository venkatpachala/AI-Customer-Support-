import os
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rag.retrieval import AdvancedRAGRetriever
from dotenv import load_dotenv

load_dotenv()

# ← Update this path to your actual PDF location
PDF_PATH = r"D:\D2C\attachments\Zepto Terms of Use.pdf"

def ingest_zepto():
    if not os.path.exists(PDF_PATH):
        print(f"PDF not found at: {PDF_PATH}")
        return

    print("Loading Zepto Terms of Use PDF...")
    loader = PyPDFLoader(PDF_PATH)
    pages = loader.load()
    print(f"Loaded {len(pages)} pages")

    # Better chunking for policy documents
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=700,
        chunk_overlap=120,
        separators=["\n\n", "\n", ". ", " ", ""]
    )

    docs = text_splitter.split_documents(pages)

    # Add clean metadata
    for i, doc in enumerate(docs):
        doc.metadata["source"] = "Zepto_Terms_of_Use.pdf"
        doc.metadata["chunk_id"] = i
        doc.metadata["document_type"] = "official_policy"

    print(f"Created {len(docs)} chunks")

    # Ingest
    retriever = AdvancedRAGRetriever()
    retriever.vectorstore.add_documents(docs)

    print("Successfully ingested Zepto Terms of Use into Pinecone")

if __name__ == "__main__":
    ingest_zepto()