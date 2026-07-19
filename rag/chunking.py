from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from typing import List

def create_policy_chunks(documents: List[Document]) -> List[Document]:
    """
    Optimized chunking for legal / policy documents
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=650,
        chunk_overlap=100,
        separators=[
            "\n\n",
            "\n",
            ". ",
            "; ",
            ", ",
            " ",
            ""
        ],
        length_function=len,
    )

    chunks = splitter.split_documents(documents)

    # Normalize metadata
    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_id"] = i
        chunk.metadata["source"] = chunk.metadata.get("source", "Zepto_Terms_of_Use.pdf")
        chunk.metadata["document_type"] = "official_policy"

        # Clean text
        chunk.page_content = chunk.page_content.strip()

    return chunks