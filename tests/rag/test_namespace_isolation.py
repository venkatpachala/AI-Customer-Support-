"""Two namespaces and two snapshots. A zepto chunk must not satisfy another brand."""
from langchain_core.documents import Document

from rag.tenant_filter import select_tenant_docs


def test_two_namespaces():
    zepto = Document(
        page_content="zepto only",
        metadata={"tenant_id": "zepto", "knowledge_snapshot": "snap-zepto", "source": "Zepto Terms"},
    )
    other = Document(
        page_content="other only",
        metadata={"tenant_id": "otherbrand", "knowledge_snapshot": "snap-other", "source": "Other Terms"},
    )
    old = Document(
        page_content="zepto other snap",
        metadata={"tenant_id": "zepto", "knowledge_snapshot": "snap-old", "source": "Zepto Terms"},
    )
    docs = [zepto, other, old]
    assert [doc.page_content for doc in select_tenant_docs(docs, "zepto", "snap-zepto")] == ["zepto only"]
    assert [doc.page_content for doc in select_tenant_docs(docs, "otherbrand", "snap-other")] == ["other only"]
    assert select_tenant_docs(docs, "zepto", "missing") == []
