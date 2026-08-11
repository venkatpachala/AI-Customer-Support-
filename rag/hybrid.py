import re
from typing import List, Dict, Tuple
from rank_bm25 import BM25Okapi
from langchain_core.documents import Document


def tokenize(text: str) -> List[str]:
    text = (text or "").lower()
    # keep dots so clause ids like 7.7.6 stay useful
    text = re.sub(r"[^a-z0-9\.\s]", " ", text)
    return [t for t in text.split() if t]


class BM25Index:
    def __init__(self, documents: List[Document]):
        self.documents = documents or []
        self.corpus = [tokenize(doc.page_content) for doc in self.documents]
        self.bm25 = BM25Okapi(self.corpus) if self.corpus else None

    def search(self, query: str, k: int = 8) -> List[Tuple[Document, float]]:
        if not self.bm25 or not self.documents:
            return []

        tokens = tokenize(query)
        if not tokens:
            return []

        scores = self.bm25.get_scores(tokens)
        ranked = sorted(
            zip(self.documents, scores),
            key=lambda x: x[1],
            reverse=True
        )
        return ranked[:k]


def _doc_key(doc: Document) -> str:
    """
    Stable identity for fusion.
    Prefer chunk_id; fallback to source/clause/page/content prefix.
    """
    md = doc.metadata or {}
    if md.get("chunk_id"):
        return str(md["chunk_id"])

    source = md.get("source_id") or md.get("source") or ""
    clause = md.get("clause") or ""
    page = md.get("page") or ""
    text = (doc.page_content or "")[:120]
    return f"{source}|{clause}|{page}|{text}"


def reciprocal_rank_fusion(
    dense_results: List[Tuple[Document, float]],
    sparse_results: List[Tuple[Document, float]],
    k: int = 20,
    rrf_k: int = 60,
    dense_weight: float = 0.5,
    sparse_weight: float = 0.5,
) -> List[Document]:
    """
    Weighted Reciprocal Rank Fusion.

    dense_weight / sparse_weight control relative influence.
    Typical trials: (0.7,0.3), (0.6,0.4), (0.5,0.5), (0.4,0.6)
    """
    scores: Dict[str, float] = {}
    doc_map: Dict[str, Document] = {}

    # Dense ranks (1-based)
    for rank, (doc, _) in enumerate(dense_results, start=1):
        key = _doc_key(doc)
        doc_map[key] = doc
        scores[key] = scores.get(key, 0.0) + dense_weight * (1.0 / (rrf_k + rank))

    # Sparse ranks (1-based)
    for rank, (doc, _) in enumerate(sparse_results, start=1):
        key = _doc_key(doc)
        doc_map[key] = doc
        scores[key] = scores.get(key, 0.0) + sparse_weight * (1.0 / (rrf_k + rank))

    ranked_keys = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

    final_docs: List[Document] = []
    for key in ranked_keys[:k]:
        doc = doc_map[key]
        # ensure metadata is mutable/copied
        doc.metadata = dict(doc.metadata or {})
        doc.metadata["hybrid_score"] = scores[key]
        final_docs.append(doc)

    return final_docs