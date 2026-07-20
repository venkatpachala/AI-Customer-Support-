from langchain_core.documents import Document

def build_citation(doc: Document) -> str:
    source = doc.metadata.get("source", "Zepto Terms of Use")
    page = doc.metadata.get("page")
    clause = doc.metadata.get("clause")
    section = doc.metadata.get("section")

    parts = [source]

    if page:
        parts.append(f"Page {page}")

    if clause:
        parts.append(f"Clause {clause}")
    elif section:
        parts.append(section)

    return ", ".join(parts)