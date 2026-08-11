import re
from typing import List, Optional
from langchain_core.documents import Document


# Matches clause-like headings:
# 8.2
# 8.1.2
# 7.7.10
# 2.1. Products
CLAUSE_HEADING_RE = re.compile(
    r"(?m)(?P<clause>\d+(?:\.\d+){0,4})\.?\s+(?P<title>[A-Z][^\n]{0,120})"
)


def _clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _page_number(doc: Document) -> Optional[int]:
    md = doc.metadata or {}
    page = md.get("page", md.get("page_number", md.get("page_num")))
    try:
        return int(float(page)) if page is not None else None
    except Exception:
        return None


def split_text_by_clauses(text: str, page: Optional[int]) -> List[Document]:
    text = _clean_text(text)
    if not text:
        return []

    matches = list(CLAUSE_HEADING_RE.finditer(text))
    if not matches:
        return [Document(
            page_content=text,
            metadata={"page": page if page is not None else "", "clause": "", "section": ""}
        )]

    chunks: List[Document] = []

    # leading text before first clause (keep if substantial)
    leading = text[:matches[0].start()].strip()
    if len(leading) > 80:
        chunks.append(Document(
            page_content=leading,
            metadata={"page": page if page is not None else "", "clause": "", "section": "preamble"}
        ))

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        if len(block) < 20:
            continue

        clause = m.group("clause").rstrip(".")
        title = (m.group("title") or "").strip()

        chunks.append(Document(
            page_content=block,
            metadata={
                "page": page if page is not None else "",
                "clause": clause,
                "section": title[:120],
            }
        ))

    return chunks


def create_policy_chunks(pages: List[Document]) -> List[Document]:
    """
    Production policy chunker:
    - prefers clause-aligned segments
    - preserves page metadata
    - falls back to whole-page chunk if no clause headings found
    """
    all_chunks: List[Document] = []

    for page_doc in pages:
        page = _page_number(page_doc)
        page_chunks = split_text_by_clauses(page_doc.page_content or "", page)
        all_chunks.extend(page_chunks)

    # final light cleanup
    cleaned: List[Document] = []
    for i, doc in enumerate(all_chunks):
        content = _clean_text(doc.page_content)
        if not content:
            continue
        md = dict(doc.metadata or {})
        md["chunk_index_local"] = i
        cleaned.append(Document(page_content=content, metadata=md))

    return cleaned