"""Lock Recall, MRR, and duplicate rate on a fake ranking. No Pinecone and no Ollama."""
from evaluation.rag.metrics import clause_in_text, duplicate_rate_at_5, first_gold_rank, recall_at, reciprocal_rank


def test_gold_in_position_2_sets_recall_and_mrr():
    chunks = [
        {"clause": "1.1", "content": "unrelated policy text", "source_id": "zepto_terms_v1", "tenant_id": "zepto"},
        {"clause": "8.1.2", "content": "damaged goods clause 8.1.2", "source_id": "zepto_terms_v1", "tenant_id": "zepto"},
        {"clause": "9.9", "content": "another clause", "source_id": "zepto_terms_v1", "tenant_id": "zepto"},
    ]
    rank = first_gold_rank(chunks, "8.1.2")
    assert rank == 2
    assert recall_at(rank, 1) == 0
    assert recall_at(rank, 3) == 1
    assert reciprocal_rank(rank) == 0.5


def test_duplicate_pair_in_top_5_sets_rate_to_1():
    shared = "same " * 50
    pair = [
        {"clause": "2.2", "content": shared + " left tail", "source_id": "zepto_terms_v1", "tenant_id": "zepto"},
        {"clause": "2.2", "content": shared + " right tail", "source_id": "zepto_terms_v1", "tenant_id": "zepto"},
        {"clause": "3.1", "content": "age rule", "source_id": "zepto_terms_v1", "tenant_id": "zepto"},
        {"clause": "5.4", "content": "payment failure", "source_id": "zepto_terms_v1", "tenant_id": "zepto"},
        {"clause": "6.1", "content": "seller prices", "source_id": "zepto_terms_v1", "tenant_id": "zepto"},
    ]
    assert duplicate_rate_at_5([pair]) == 1


def test_clause_period_matches_and_longer_number_does_not():
    assert clause_in_text("8.1.1.1. wrong item being delivered", "8.1.1.1")
    assert not clause_in_text("8.1.1.1. wrong item being delivered", "8.1.1")
    assert not clause_in_text("see clause 8.1.2 for damage", "8.1")
