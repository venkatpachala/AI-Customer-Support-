import re
from typing import List, Dict, Tuple
from rank_bm25 import BM25Okapi
from langchain_core.documents import Document


def tokenize(text: str) -> List[str]:
    text = text.lower()
    text = re.sub(r'[^a-z0-9\.\s]', ' ', text)
    return [t for t in text.split() if t]


class BM25Index:
    def __init__(self, documents: List[Document]):
        self.documents = documents
        self.corpus = [tokenize(doc.page_content) for doc in documents]
        self.bm25 = BM25Okapi(self.corpus) if self.corpus else None

    def search(self, query: str, k: int = 8) -> List[Tuple[Document, float]]:
        if not self.bm25 or not self.documents:
            return []

        tokens = tokenize(query)
        scores = self.bm25.get_scores(tokens)

        ranked = sorted(
            zip(self.documents, scores),
            key=lambda x: x[1],
            reverse=True
        )
        return ranked[:k]


def reciprocal_rank_fusion(
    dense_results: List[Tuple[Document, float]],
    sparse_results: List[Tuple[Document, float]],
    k: int = 4,
    rrf_k: int = 60
) -> List[Document]:
    """
    Fuse dense + sparse rankings using Reciprocal Rank Fusion.
    """
    scores: Dict[str, float] = {}
    doc_map: Dict[str, Document] = {}

    def doc_key(doc: Document) -> str:
        return doc.metadata.get("chunk_id") or doc.page_content[:80]

    # Dense ranks
    for rank, (doc, _) in enumerate(dense_results):
        key = doc_key(doc)
        doc_map[key] = doc
        scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank + 1)

    # Sparse ranks
    for rank, (doc, _) in enumerate(sparse_results):
        key = doc_key(doc)
        doc_map[key] = doc
        scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank + 1)

    fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    final_docs = []
    for key, score in fused[:k]:
        doc = doc_map[key]
        doc.metadata["hybrid_score"] = score
        final_docs.append(doc)

    return final_docs