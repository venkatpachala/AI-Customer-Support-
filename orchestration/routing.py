"""
orchestration/routing.py — Phase 3 three-way routing.

Routes after supervisor decision:
  knowledge    → hitl_check → qa      (RAG + QA)
  transactional → identity_gate       (Shopify direct lookup)
  action        → identity_gate       (full planner/executor flow)
  conversational → hitl_check → qa   (direct conversational reply)
"""
from typing import Dict, Any


# ── Intent sets for reference ────────────────────────────────────────────────

KNOWLEDGE_INTENTS = {"policy_query", "policy", "faq", "general_query", "policy_question"}
TRANSACTIONAL_INTENTS = {"track", "order_status"}
ACTION_INTENTS = {"return", "refund", "cancel", "replace", "replacement", "damaged_return", "damage"}
CONVERSATIONAL_INTENTS = {"general", "greeting", "smalltalk", "thanks", "unknown"}


def _intent_type_from_state(state: Dict[str, Any]) -> str:
    """Resolve intent_type — prefer explicit field, fallback to intent mapping."""
    it = (state.get("intent_type") or "").lower().strip()
    if it in ("knowledge", "transactional", "action", "conversational"):
        return it

    intent = (
        state.get("intent")
        or (state.get("current_plan") or {}).get("intent")
        or ""
    ).lower().strip()

    if intent in KNOWLEDGE_INTENTS:
        return "knowledge"
    if intent in TRANSACTIONAL_INTENTS:
        return "transactional"
    if intent in ACTION_INTENTS:
        return "action"
    return "conversational"


def after_supervisor_route(state: Dict[str, Any]) -> str:
    """
    Primary routing decision after supervisor:
    - blocked / escalated → end
    - knowledge           → hitl_check (→ qa with RAG context)
    - transactional       → identity_gate (→ direct Shopify lookup via planner)
    - action              → identity_gate (→ full planner/executor/verifier)
    - conversational      → hitl_check (→ qa for direct reply)
    """
    if state.get("blocked"):
        return "end"
    if state.get("needs_escalation"):
        return "end"

    risk = (state.get("risk_level") or "low").lower()
    if risk in ("high", "critical"):
        return "end"

    intent_type = _intent_type_from_state(state)

    if intent_type in ("transactional", "action"):
        return "identity_gate"

    # knowledge or conversational → policy fast-path through hitl → qa
    return "hitl_check"


# Legacy compatibility alias
def is_policy_fast_path(state: Dict[str, Any]) -> bool:
    """True when the request should bypass the planner and go directly to QA via HITL."""
    it = _intent_type_from_state(state)
    return it in ("knowledge", "conversational")