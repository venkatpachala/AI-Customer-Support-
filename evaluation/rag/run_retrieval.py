"""Official hybrid retrieval benchmark. A missing BM25 corpus exits 1.

Dense-only runs are not written as rag_benchmark_latest.json.
"""
from __future__ import annotations

import hashlib
import json
import pickle
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

load_dotenv()

from evaluation.rag.metrics import (
    duplicate_rate_at_5,
    first_gold_rank,
    mean,
    query_has_duplicate,
    recall_at,
    reciprocal_rank,
    tenant_leak_rate,
)
from evaluation.rag.validate import failures_of
from rag.retrieval import AdvancedRAGRetriever
from rag.tenant_filter import pinecone_tenant_filter

ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = ROOT / "evaluation" / "rag" / "dataset.json"
BM25_PATH = ROOT / "rag" / "bm25_corpus_zepto.pkl"
REPORT_DIR = ROOT / "evaluation" / "reports"
LATEST = REPORT_DIR / "rag_benchmark_latest.json"


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def _chunks(docs: List[Any]) -> List[Dict[str, Any]]:
    rows = []
    for doc in docs:
        metadata = dict(getattr(doc, "metadata", {}) or {})
        rows.append({
            "clause": metadata.get("clause"),
            "content": getattr(doc, "page_content", "") or "",
            "source_id": metadata.get("source_id"),
            "tenant_id": metadata.get("tenant_id"),
            "page": metadata.get("page", metadata.get("page_number")),
            "chunk_id": metadata.get("chunk_id"),
        })
    return rows


def _round(value: float) -> float:
    return round(float(value), 4)


def run() -> Path:
    if not BM25_PATH.is_file():
        raise SystemExit(f"missing {BM25_PATH}")
    if not DATASET_PATH.is_file():
        raise SystemExit(f"missing {DATASET_PATH}")

    dataset_bytes = DATASET_PATH.read_bytes()
    rows = json.loads(dataset_bytes.decode("utf-8"))
    answerable = [row for row in rows if row.get("answerable", True)]
    retriever = AdvancedRAGRetriever()
    with BM25_PATH.open("rb") as handle:
        corpus = pickle.load(handle)
    retriever.load_bm25_documents(corpus)
    embedding_model = getattr(getattr(retriever, "embeddings", None), "model", None) or "text-embedding-3-large"

    queries = []
    rankings = []
    for row in answerable:
        question = row["question"]
        docs = retriever.retrieve(
            question,
            k=20,
            final_k=10,
            use_hybrid=True,
            metadata_filter=pinecone_tenant_filter(row.get("tenant_id") or "zepto"),
        ) or []
        stats = dict(getattr(retriever, "last_retrieval", {}) or {})
        dense_n = int(stats.get("dense_n") or 0)
        sparse_n = int(stats.get("sparse_n") or 0)
        fusion = str(stats.get("fusion") or "dense_only")
        print(f"fusion={fusion} dense_n={dense_n} sparse_n={sparse_n}")
        chunks = _chunks(docs)
        rankings.append(chunks)
        rank = first_gold_rank(chunks, str(row.get("gold_clause") or ""))
        hit = chunks[rank - 1] if rank else {}
        queries.append({
            "id": row.get("id"),
            "tenant_id": row.get("tenant_id") or "zepto",
            "question": question,
            "answerable": True,
            "gold_clause": row.get("gold_clause"),
            "gold_page": row.get("gold_page"),
            "page": hit.get("page"),
            "rank": rank,
            "clause": hit.get("clause"),
            "source_id": hit.get("source_id"),
            "chunk_id": hit.get("chunk_id"),
            "duplicate": query_has_duplicate(chunks, 5),
            "fusion": fusion,
            "hybrid": bool(stats.get("hybrid", True)),
            "dense_n": dense_n,
            "sparse_n": sparse_n,
            "recall@1": recall_at(rank, 1),
            "recall@3": recall_at(rank, 3),
            "recall@5": recall_at(rank, 5),
            "recall@10": recall_at(rank, 10),
            "mrr": reciprocal_rank(rank),
            "scored_chunks": [
                {
                    "rank": index,
                    "clause": chunk.get("clause"),
                    "content": chunk.get("content"),
                    "source_id": chunk.get("source_id"),
                    "tenant_id": chunk.get("tenant_id"),
                    "page": chunk.get("page"),
                    "chunk_id": chunk.get("chunk_id"),
                }
                for index, chunk in enumerate(chunks, start=1)
            ],
            "top5": [
                {
                    "rank": index,
                    "clause": chunk.get("clause"),
                    "source_id": chunk.get("source_id"),
                    "tenant_id": chunk.get("tenant_id"),
                    "page": chunk.get("page"),
                    "chunk_id": chunk.get("chunk_id"),
                }
                for index, chunk in enumerate(chunks[:5], start=1)
            ],
        })

    misses = [row["id"] for row in queries if row["recall@5"] < 1]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = REPORT_DIR / f"rag_benchmark_{stamp}.json"
    report = {
        "created_at": stamp,
        "report_path": str(report_path),
        "git_commit": _git_commit(),
        "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "embedding_model": embedding_model,
        "bm25_corpus": "rag/bm25_corpus_zepto.pkl",
        "hybrid": True,
        "n_answerable": len(queries),
        "n_unanswerable": sum(1 for row in rows if row.get("answerable") is False),
        "recall@1": _round(mean(row["recall@1"] for row in queries)),
        "recall@3": _round(mean(row["recall@3"] for row in queries)),
        "recall@5": _round(mean(row["recall@5"] for row in queries)),
        "recall@10": _round(mean(row["recall@10"] for row in queries)),
        "mrr": _round(mean(row["mrr"] for row in queries)),
        "duplicate_rate@5": _round(duplicate_rate_at_5(rankings)),
        "tenant_leak": tenant_leak_rate(rankings, "zepto", tenant_filter_on=True),
        "failures": misses,
        "queries": queries,
    }
    if isinstance(report["tenant_leak"], float):
        report["tenant_leak"] = _round(report["tenant_leak"])
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {report_path}")
    reasons = failures_of(report)
    if reasons:
        print("VALIDATE FAIL")
        for reason in reasons:
            print(f"- {reason}")
        raise SystemExit(1)
    shutil.copyfile(report_path, LATEST)
    print(f"copied {LATEST}")
    return report_path


def main() -> None:
    run()


if __name__ == "__main__":
    main()
