from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rag.retrieval import AdvancedRAGRetriever
import os

# Path to the PDF (update this path if needed)
PDF_PATH = r"D:\D2C\attachments\Zepto Terms of Use.pdf"   # ← Change this to your actual path

def ingest_zepto_policy():
    if not os.path.exists(PDF_PATH):
        print(f"❌ File not found: {PDF_PATH}")
        print("Please update the PDF_PATH variable with the correct location.")
        return

    print("Loading full Zepto Terms of Use PDF...")
    loader = PyPDFLoader(PDF_PATH)
    documents = loader.load()

    print(f"Loaded {len(documents)} pages from the PDF.")

    # Split into chunks
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=150,
        separators=["\n\n", "\n", ".", " ", ""]
    )
    
    split_docs = text_splitter.split_documents(documents)

    # Add better metadata
    for i, doc in enumerate(split_docs):
        doc.metadata["source"] = "Zepto_Terms_of_Use.pdf"
        doc.metadata["document_type"] = "official_policy"
        doc.metadata["chunk_id"] = i

    # Ingest into Pinecone
    retriever = AdvancedRAGRetriever()
    retriever.vectorstore.add_documents(split_docs)

    print(f"✅ Successfully ingested {len(split_docs)} chunks from the full Zepto Terms of Use document!")

if __name__ == "__main__":
    ingest_zepto_policy()