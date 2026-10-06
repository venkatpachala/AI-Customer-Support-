"""Exit 1 unless the frozen hybrid benchmark still holds. Does not change gold clauses."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[2]
LATEST = ROOT / "evaluation" / "reports" / "rag_benchmark_latest.json"
KNOWN_MISS = "policy_service_area_1"


def load_report(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        report = json.load(handle)
    if not isinstance(report, dict):
        raise SystemExit("report is not an object")
    return report


def failures_of(report: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []
    queries = list(report.get("queries") or [])
    answerable = [row for row in queries if row.get("answerable", True) and row.get("gold_clause")]
    if report.get("n_answerable") != 39 or len(answerable) != 39:
        reasons.append(f"n_answerable={report.get('n_answerable')} labeled={len(answerable)}")
    if any(not str(row.get("gold_clause") or "").strip() for row in answerable):
        reasons.append("answerable row missing gold_clause")
    if report.get("hybrid") is not True:
        reasons.append("hybrid is not true")
    for row in queries:
        if row.get("hybrid") is not True or int(row.get("sparse_n") or 0) <= 0 or int(row.get("dense_n") or 0) <= 0:
            reasons.append(
                f"{row.get('id')} dense_n={row.get('dense_n')} sparse_n={row.get('sparse_n')} hybrid={row.get('hybrid')}"
            )
            break
        if row.get("fusion") != "rrf":
            reasons.append(f"{row.get('id')} fusion={row.get('fusion')}")
            break
    leak = report.get("tenant_leak")
    if leak not in (0, 0.0, "not_measured"):
        reasons.append(f"tenant_leak={leak}")
    recall5 = float(report.get("recall@5") or 0)
    mrr = float(report.get("mrr") or 0)
    if recall5 < 0.95:
        reasons.append(f"recall@5={recall5}")
    if mrr < 0.75:
        reasons.append(f"mrr={mrr}")
    listed = list(report.get("failures") or [])
    missed = [row.get("id") for row in answerable if float(row.get("recall@5") or 0) < 1]
    if KNOWN_MISS in missed and KNOWN_MISS not in listed:
        reasons.append(f"{KNOWN_MISS} missed top 5 and is not listed under failures")
    for key in ("report_path", "git_commit", "dataset_sha256", "embedding_model"):
        if not report.get(key):
            reasons.append(f"missing {key}")
    return reasons


def resume_line(report: Dict[str, Any]) -> str:
    misses = list(report.get("failures") or [])
    n = int(report.get("n_answerable") or 0)
    recall5 = float(report.get("recall@5") or 0)
    mrr = float(report.get("mrr") or 0)
    return (
        f"On a frozen {n}-question Zepto policy set, hybrid retrieval "
        f"(dense + BM25 + RRF + dedup + rerank) reached Recall@5 {recall5:.4f} "
        f"and MRR {mrr:.4f}; {len(misses)}/{n} gold clauses missed top 5."
    )


def main(argv: List[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    path = Path(args[0]) if args else LATEST
    if not path.is_file():
        print(f"missing report {path}")
        return 1
    report = load_report(path)
    reasons = failures_of(report)
    print(
        f"n_answerable={report.get('n_answerable')} "
        f"recall@1={report.get('recall@1')} recall@3={report.get('recall@3')} "
        f"recall@5={report.get('recall@5')} recall@10={report.get('recall@10')} "
        f"mrr={report.get('mrr')} duplicate_rate@5={report.get('duplicate_rate@5')} "
        f"tenant_leak={report.get('tenant_leak')} failures={report.get('failures')}"
    )
    if report.get("citation_hit") is not None:
        print(
            f"citation_hit={report.get('citation_hit')} "
            f"faithfulness={report.get('faithfulness')} "
            f"abstention={report.get('abstention')}"
        )
    if reasons:
        print("VALIDATE FAIL")
        for reason in reasons:
            print(f"- {reason}")
        return 1
    print("VALIDATE PASS")
    print(resume_line(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
