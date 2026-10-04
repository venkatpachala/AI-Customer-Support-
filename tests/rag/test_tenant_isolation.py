"""Tenant filter for retrieval. No Pinecone client."""
from langchain_core.documents import Document

from rag.ingestion import normalize_chunks
from rag.tenant_filter import dedup_key, pinecone_tenant_filter, select_tenant_docs


def test_chunk_metadata_carries_tenant_and_stable_id():
    chunks = normalize_chunks(
        [Document(page_content="Clause 4 refunds", metadata={"page": 2, "clause": "4.1"})],
        tenant_id="zepto",
        knowledge_snapshot="zepto-terms-2026-08",
    )
    metadata = chunks[0].metadata
    assert metadata["tenant_id"] == "zepto"
    assert metadata["source_id"] == "zepto_terms_v1"
    assert metadata["chunk_id"] == "zepto_terms_v1:c0"
    assert metadata["knowledge_snapshot"] == "zepto-terms-2026-08"
    assert metadata["clause"] == "4.1"


def test_other_tenant_filter_drops_zepto_chunks():
    zepto = Document(page_content="zepto clause", metadata={"tenant_id": "zepto", "source": "Zepto Terms of Use", "chunk_id": "zepto_terms_v1:c0"})
    other = Document(page_content="other clause", metadata={"tenant_id": "other", "source": "Other Terms", "chunk_id": "other_terms:c0"})
    path_copy = Document(page_content="copy", metadata={"tenant_id": "zepto", "source": r"D:\D2C\attachments\Zepto Terms of Use.pdf", "chunk_id": "zepto_terms_v1:c1"})
    kept = select_tenant_docs([zepto, other, path_copy], "other")
    assert [doc.metadata["chunk_id"] for doc in kept] == ["other_terms:c0"]
    assert pinecone_tenant_filter("other") == {"tenant_id": "other"}


def test_dedup_key_ignores_file_path():
    left = dedup_key("zepto_terms_v1", "4.1", "clause 4 refunds")
    right = dedup_key("zepto_terms_v1", "4.1", "clause 4 refunds")
    assert left == right
    assert "attachments" not in left
    assert "\\" not in left
