import json
import re
import pickle
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv(override=True)

from rag.retrieval import AdvancedRAGRetriever

ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = Path(__file__).parent / "dataset.json"
REPORT_DIR = ROOT / "evaluation" / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def load_dataset() -> List[Dict[str, Any]]:
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def clause_in_text(text: str, clause: Optional[str]) -> bool:
    if not clause:
        return False
    t = norm(text)
    c = norm(str(clause)).rstrip(".")
    patterns = [
        rf"\b{re.escape(c)}\b",
        rf"clause\s+{re.escape(c)}\b",
    ]
    return any(re.search(p, t) for p in patterns)


def page_of(doc: Any) -> Optional[int]:
    md = getattr(doc, "metadata", {}) or {}
    page = md.get("page", md.get("page_number", md.get("page_num")))
    try:
        if page is None:
            return None
        return int(float(page))
    except Exception:
        return None


def find_gold_rank(
    docs: List[Any],
    gold_clause: Optional[str],
    gold_page: Optional[int] = None,
) -> Optional[int]:
    """
    Rank is 1-based.

    PRIMARY success:
      - metadata.clause == gold_clause OR
      - gold_clause appears in page_content

    Page is diagnostic only and is NOT used for success when gold_clause exists.
    """
    if not gold_clause:
        return None

    gold = str(gold_clause).strip().rstrip(".")

    for i, d in enumerate(docs, start=1):
        content = getattr(d, "page_content", "") or ""
        md = getattr(d, "metadata", {}) or {}
        meta_clause = str(md.get("clause") or "").strip().rstrip(".")

        if meta_clause == gold:
            return i
        if clause_in_text(content, gold):
            return i

    return None


def detect_duplicates(docs: List[Any]) -> int:
    seen = set()
    dupes = 0
    for d in docs:
        key = norm((getattr(d, "page_content", "") or "")[:200])
        if key in seen:
            dupes += 1
        else:
            seen.add(key)
    return dupes


def evaluate_one(row: Dict[str, Any], docs: List[Any], ks=(1, 3, 5)) -> Dict[str, Any]:
    qid = row.get("id")
    question = row.get("question")
    answerable = bool(row.get("answerable", True))
    gold_clause = row.get("gold_clause")
    gold_page = row.get("gold_page")

    # Clause-primary labeling only
    labeled = bool(gold_clause)

    max_k = max(ks)
    top_docs = docs[:max_k]
    rank = find_gold_rank(top_docs, gold_clause, gold_page) if (labeled and answerable) else None

    recalls = {}
    for k in ks:
        if not answerable or not labeled:
            recalls[f"recall@{k}"] = None
        else:
            recalls[f"recall@{k}"] = 1.0 if (rank is not None and rank <= k) else 0.0

    mrr = None
    if answerable and labeled:
        mrr = (1.0 / rank) if rank else 0.0

    if not labeled:
        bucket = "unlabeled"
    elif not answerable:
        bucket = "unanswerable"
    elif rank == 1:
        bucket = "retrieved_rank1"
    elif rank is not None and rank <= 3:
        bucket = "retrieved_rank2_3"
    elif rank is not None:
        bucket = "retrieved_rank_gt3"
    else:
        bucket = "missed_in_top_k"

    return {
        "id": qid,
        "question": question,
        "answerable": answerable,
        "labeled": labeled,
        "gold_clause": gold_clause,
        "gold_page": gold_page,  # diagnostic only
        "gold_rank": rank,
        "mrr": mrr,
        **recalls,
        "bucket": bucket,
        "duplicate_chunks_in_topk": detect_duplicates(top_docs),
        "top_previews": [
            {
                "rank": i + 1,
                "page": page_of(d),
                "clause": (getattr(d, "metadata", {}) or {}).get("clause"),
                "source": (getattr(d, "metadata", {}) or {}).get("source"),
                "preview": (getattr(d, "page_content", "") or "")[:220],
                "citation": (getattr(d, "metadata", {}) or {}).get("citation"),
            }
            for i, d in enumerate(top_docs[:5])
        ],
    }


def safe_mean(vals: List[Optional[float]]) -> Optional[float]:
    xs = [v for v in vals if v is not None]
    if not xs:
        return None
    return round(sum(xs) / len(xs), 4)


def build_retriever() -> AdvancedRAGRetriever:
    retriever = AdvancedRAGRetriever()
    bm25_path = Path("rag/bm25_corpus.pkl")
    if bm25_path.exists():
        with open(bm25_path, "rb") as f:
            docs = pickle.load(f)
        retriever.load_bm25_documents(docs)
        print(f"BM25 loaded with {len(docs)} docs")
    else:
        print("WARNING: bm25_corpus.pkl not found — hybrid will fall back to dense-only")
    return retriever


def main():
    rows = load_dataset()
    retriever = build_retriever()
    ks = (1, 3, 5)

    results = []
    print(f"Running production retrieval eval on {len(rows)} questions")
    print("Gold matching mode: CLAUSE-PRIMARY (page ignored for success)")

    for row in rows:
        q = row["question"]
        print(f"- {row.get('id')}")
        docs = retriever.retrieve(q, k=8, final_k=5, use_hybrid=True) or []
        results.append(evaluate_one(row, docs, ks=ks))

    labeled_answerable = [r for r in results if r["answerable"] and r["labeled"]]
    unlabeled = [r for r in results if not r["labeled"]]
    unanswerable = [r for r in results if r["labeled"] and not r["answerable"]]

    summary = {
        "n_total": len(results),
        "n_labeled_answerable": len(labeled_answerable),
        "n_unlabeled": len(unlabeled),
        "n_unanswerable": len(unanswerable),
        "recall@1": safe_mean([r["recall@1"] for r in labeled_answerable]),
        "recall@3": safe_mean([r["recall@3"] for r in labeled_answerable]),
        "recall@5": safe_mean([r["recall@5"] for r in labeled_answerable]),
        "mrr": safe_mean([r["mrr"] for r in labeled_answerable]),
        "buckets": {},
        "note": "Metrics on labeled answerable only; success = gold_clause hit in content/metadata",
    }

    for r in results:
        summary["buckets"][r["bucket"]] = summary["buckets"].get(r["bucket"], 0) + 1

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = REPORT_DIR / f"retrieval_eval_{stamp}.json"
    payload = {
        "created_at": stamp,
        "summary": summary,
        "results": results,
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print("\n===== RETRIEVAL EVAL SUMMARY =====")
    print(json.dumps(summary, indent=2))
    print(f"Report saved to: {out}")

    if summary["n_labeled_answerable"] == 0:
        print("\nWARNING: No labeled answerable questions. Add gold_clause values and rerun.")


if __name__ == "__main__":
    main()