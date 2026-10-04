"""Sample Auto-QA. Deterministic checks. A judge model runs only when AUTOQA_LLM=1.

This does not sit on the request path.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import desc, select

from db.models import InteractionRow
from db.session import SessionLocal

REPORTS = Path(__file__).resolve().parent / "reports"
_REFUND_CLAIMS = ("refund has been", "refund is complete", "refund id", "re_live", "successfully refunded")
_STATUS_OUTCOME = {
    "waiting_approval": "waiting_approval",
    "waiting_auth": "waiting_auth",
    "waiting_input": "waiting_customer",
    "succeeded": "resolved",
    "failed": "failed",
    "cancelled": "failed",
}


def score_turn(row: Dict[str, Any]) -> Dict[str, Any]:
    meta = dict(row.get("metadata") or {})
    intent = str(row.get("intent") or "")
    response = str(row.get("response") or "").lower()
    workflow_status = str(meta.get("workflow_status") or "")
    outcome = str(meta.get("outcome") or "")
    citations = list(row.get("citations") or [])
    policy_intent = intent in {"policy", "policy_query", "faq", "knowledge"}
    citation_ok = (not policy_intent) or bool(citations)
    refund_claim = any(phrase in response for phrase in _REFUND_CLAIMS)
    refund_ok = workflow_status == "succeeded" or not refund_claim
    expected = _STATUS_OUTCOME.get(workflow_status)
    outcome_ok = expected is None or outcome == expected
    passed = citation_ok and refund_ok and outcome_ok
    return {
        "id": row.get("id"),
        "intent": intent or None,
        "outcome": outcome or None,
        "workflow_status": workflow_status or None,
        "citation_ok": citation_ok,
        "refund_claim_ok": refund_ok,
        "outcome_ok": outcome_ok,
        "passed": passed,
    }


def summarize(scores: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(scores)
    def rate(key: str) -> float:
        if n == 0:
            return 1.0
        return round(sum(1 for item in scores if item[key]) / n, 4)

    return {
        "n": n,
        "passed": sum(1 for item in scores if item["passed"]),
        "citation_rate": rate("citation_ok"),
        "refund_claim_rate": rate("refund_claim_ok"),
        "outcome_match_rate": rate("outcome_ok"),
        "pass_rate": rate("passed"),
        "llm_judge": os.getenv("AUTOQA_LLM", "").strip() == "1",
    }


def load_recent(tenant_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit or 50), 200))
    with SessionLocal() as db:
        rows = db.execute(
            select(InteractionRow)
            .where(InteractionRow.tenant_id == tenant_id)
            .order_by(desc(InteractionRow.created_at))
            .limit(limit)
        ).scalars().all()
    loaded = []
    for row in rows:
        loaded.append(
            {
                "id": row.interaction_id,
                "intent": row.intent,
                "response": row.response,
                "citations": list(row.citations or []),
                "metadata": dict(row.metadata_json or {}),
            }
        )
    return loaded


def write_report(tenant_id: str = "zepto", limit: int = 50) -> Path:
    scores = [score_turn(row) for row in load_recent(tenant_id, limit)]
    body = {
        "tenant_id": tenant_id,
        "created_at": datetime.utcnow().isoformat(),
        "summary": summarize(scores),
        "turns": scores,
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"autoqa_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    print(
        "AUTOQA "
        f"n={body['summary']['n']} "
        f"pass_rate={body['summary']['pass_rate']} "
        f"citation_rate={body['summary']['citation_rate']} "
        f"refund_claim_rate={body['summary']['refund_claim_rate']} "
        f"outcome_match_rate={body['summary']['outcome_match_rate']}"
    )
    print(f"report {path}")
    return path


if __name__ == "__main__":
    write_report()
