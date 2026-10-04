"""Auto-QA rates. No judge model."""
from evaluation.autoqa import score_turn, summarize


def test_autoqa_flags_refund_claim_and_missing_policy_citation():
    scores = [
        score_turn({
            "id": "1",
            "intent": "policy",
            "response": "See the terms.",
            "citations": ["Zepto Terms of Use, Clause 4"],
            "metadata": {"workflow_status": "", "outcome": "answered"},
        }),
        score_turn({
            "id": "2",
            "intent": "refund",
            "response": "Your refund is complete. Refund id re_live_1",
            "citations": [],
            "metadata": {"workflow_status": "waiting_approval", "outcome": "waiting_approval"},
        }),
        score_turn({
            "id": "3",
            "intent": "refund",
            "response": "A human will review this refund.",
            "citations": [],
            "metadata": {"workflow_status": "waiting_approval", "outcome": "answered"},
        }),
    ]
    summary = summarize(scores)
    assert scores[0]["citation_ok"] is True
    assert scores[1]["refund_claim_ok"] is False
    assert scores[2]["outcome_ok"] is False
    assert summary["n"] == 3
    assert summary["pass_rate"] < 1
    assert summary["llm_judge"] is False
