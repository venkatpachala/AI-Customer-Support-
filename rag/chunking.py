from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from typing import List
import re

def clean_text(text: str) -> str:
    """Remove excessive whitespace and noise"""
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = text.strip()
    return text

def create_policy_chunks(documents: List[Document]) -> List[Document]:
    """
    Optimized chunking for legal / policy documents
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=600,
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

    raw_chunks = splitter.split_documents(documents)
    cleaned_chunks = []

    for i, chunk in enumerate(raw_chunks):
        content = clean_text(chunk.page_content)

        # Skip very short or low-value chunks
        if len(content) < 80:
            continue

        # Skip pure header / index style chunks
        if content.lower().startswith(("table of contents", "index", "page ")) and len(content) < 150:
            continue

        chunk.page_content = content
        chunk.metadata["chunk_id"] = i
        chunk.metadata["source"] = "Zepto_Terms_of_Use.pdf"
        chunk.metadata["document_type"] = "official_policy"

        cleaned_chunks.append(chunk)

    return cleaned_chunks