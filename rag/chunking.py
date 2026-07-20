import re
from typing import List, Optional
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


def clean_text(text: str) -> str:
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text.strip()


def extract_clause_number(text: str) -> str:
    """
    Detect clause-like numbers:
    7.7, 7.7.1, 7.7.10, 8.2.3 etc.
    Returns empty string if not found.
    """
    match = re.search(r'\b(\d+\.\d+(?:\.\d+){0,2})\b', text)
    return match.group(1) if match else ""


def extract_section_title(text: str) -> str:
    """
    Heuristic for section headings.
    Returns empty string if not found.
    """
    lines = text.split("\n")
    for line in lines[:3]:
        line = line.strip()
        if 5 < len(line) < 120 and (
            line.isupper()
            or re.match(r'^\d+(\.\d+)*\s+[A-Z]', line)
            or "return" in line.lower()
            or "refund" in line.lower()
            or "cancellation" in line.lower()
            or "delivery" in line.lower()
        ):
            return line
    return ""


def create_policy_chunks(documents: List[Document]) -> List[Document]:
    """
    Structure-aware chunking for policy / legal PDFs.
    Preserves page, section, and clause metadata.
    Pinecone-safe: never stores None.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=550,
        chunk_overlap=80,
        separators=["\n\n", "\n", ". ", "; ", ", ", " ", ""],
        length_function=len,
    )

    raw_chunks = splitter.split_documents(documents)
    final_chunks = []

    for i, chunk in enumerate(raw_chunks):
        content = clean_text(chunk.page_content)
        if len(content) < 60:
            continue

        # PyPDFLoader page is usually 0-indexed
        page = chunk.metadata.get("page", 0)
        if isinstance(page, int):
            page = page + 1
        else:
            page = 0

        clause = extract_clause_number(content)
        section = extract_section_title(content)

        chunk.page_content = content
        chunk.metadata = {
            "source": "Zepto Terms of Use",
            "page": page,
            "section": section,          # always string
            "clause": clause,            # always string
            "chunk_id": f"p{page}-c{clause or i}-{i}",
            "document_type": "official_policy"
        }

        final_chunks.append(chunk)

    return final_chunks