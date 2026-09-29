"""
orchestration/supervisor.py — Context-Aware Conversational Supervisor (Phase 3).

Phase 3 changes:
- Reads conversation history (active_intent, conversation_turns, pending_action)
- Detects affirmations ("yes", "ok", "sure") and continues active intent rather than re-classifying
- Produces tripartite intent_type: knowledge | transactional | action | conversational
- RAG runs in parallel ONLY for knowledge queries (not on identity turns, greetings, affirmations)
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional

from langchain_core.prompts import ChatPromptTemplate
from observability.logging import log_event
from orchestration.state import AgentState
from common.messages import get_last_user_message
from common.llm import get_supervisor_llm

llm = get_supervisor_llm()

# ---------------------------------------------------------------------------
# Affirmation detection — handles "Yes", "Ok", "Sure", "Go ahead", etc.
# ---------------------------------------------------------------------------

_AFFIRMATION_TOKENS = {
    "yes", "yeah", "yep", "yup", "ok", "okay", "sure", "go ahead",
    "please", "please do", "go", "proceed", "do it", "alright",
    "sounds good", "that works", "why not", "definitely", "absolutely",
}


def _is_affirmation(text: str) -> bool:
    t = (text or "").lower().strip().rstrip("!.,?")
    return t in _AFFIRMATION_TOKENS or len(t.split()) <= 3 and any(tok in t for tok in _AFFIRMATION_TOKENS)


def _extract_intent_type(intent: str) -> str:
    """Map intent to tripartite routing bucket."""
    if intent in ("policy_query", "faq", "policy"):
        return "knowledge"
    if intent in ("track", "order_status"):
        return "transactional"
    if intent in ("return", "refund", "cancel", "replace", "replacement", "damage", "damaged_return"):
        return "action"
    return "conversational"


# ---------------------------------------------------------------------------
# Context-aware prompt — receives conversation history
# ---------------------------------------------------------------------------

supervisor_prompt = ChatPromptTemplate.from_template(
    """You are a customer support supervisor for Zepto, a quick-commerce platform.

You will classify the customer's CURRENT message, taking into account the CONVERSATION CONTEXT below.

CONVERSATION CONTEXT:
- Active intent from previous turn: {active_intent}
- Active case type: {active_case_type}
- Pending action: {pending_action}
- Auth level: {auth_level}
- Recent conversation (last 3 turns):
{recent_history}

CURRENT MESSAGE: {query}

CLASSIFICATION RULES:

1. If the message is an AFFIRMATION ("yes", "ok", "sure", "go ahead", "please") and there is an active_intent,
   return the SAME intent with is_continuation=true and affirmation_of=<active_intent>.

2. Classify into ONE intent:
   - "policy_query": Questions about store policies, return/refund rules, damage policies, delivery terms.
     Examples: "What is your return policy?", "Can I return a damaged product?", "How long do I have?"
   - "return": Action to return an order. Examples: "I want to return my order", "Return order 12345"
   - "refund": Action to request a refund. Examples: "I want a refund", "Refund my order"
   - "cancel": Action to cancel an order. Examples: "Cancel my order", "Cancel order 12345"
   - "track": Action to track/locate an order. Examples: "Where is my order?", "Track my package"
   - "damaged_return": Customer received damaged product and wants return. "My order arrived damaged."
   - "general": Greeting, smalltalk, thanks. Examples: "Hi", "Thank you", "That's great"

3. Classify intent_type:
   - "knowledge": policy_query → use RAG
   - "transactional": track → direct Shopify lookup
   - "action": return | refund | cancel | damaged_return → identity gate → planner → executor
   - "conversational": general | affirmations without active_intent

4. Risk: Only "high" for clear fraud, threats, abuse language.

Return ONLY valid JSON:
{{
  "intent": "...",
  "intent_type": "knowledge|transactional|action|conversational",
  "risk": "low|medium|high",
  "needs_escalation": false,
  "is_continuation": false,
  "affirmation_of": null,
  "confidence": 0.95
}}
"""
)


def supervisor_node(state: AgentState) -> Dict:
    request_id = state.get("request_id", "unknown")
    log_event("supervisor_started", request_id, node="supervisor")

    query = get_last_user_message(state.get("messages", []))
    memory_context = state.get("memory_context") or {}

    # Pull conversation context
    active_intent = (
        state.get("active_intent")
        or memory_context.get("active_intent")
        or memory_context.get("issue_type")
        or "none"
    )
    active_case_type = state.get("active_case_type") or memory_context.get("active_case_type") or "none"
    pending_action = state.get("pending_action") or memory_context.get("pending_action") or "none"
    auth_level = state.get("auth_level") or memory_context.get("auth_level") or "anonymous"

    # Build recent history string
    turns = memory_context.get("conversation_turns") or []
    recent = "\n".join(
        f"  {t.get('role', '?')}: {t.get('text', '')[:100]}"
        for t in turns[-3:]
    ) or "  (no prior turns)"

    # Fast-path: affirmation + active intent → continue without LLM call
    if _is_affirmation(query) and active_intent and active_intent != "none":
        intent = active_intent
        is_continuation = True
        affirmation_of = active_intent
        risk = "low"
        needs_escalation = False
        intent_type = _extract_intent_type(intent)
        log_event("supervisor_affirmation_continuation", request_id, node="supervisor",
                  data={"continued_intent": intent})
    else:
        try:
            response = llm.invoke(supervisor_prompt.format(
                query=query,
                active_intent=active_intent,
                active_case_type=active_case_type,
                pending_action=pending_action,
                auth_level=auth_level,
                recent_history=recent,
            ))
            content = response.content.strip()
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                content = json_match.group(0)
            data = json.loads(content)

            intent = data.get("intent", "general")
            intent_type = data.get("intent_type") or _extract_intent_type(intent)
            risk = data.get("risk", "low")
            needs_escalation = bool(data.get("needs_escalation", False))
            is_continuation = bool(data.get("is_continuation", False))
            affirmation_of = data.get("affirmation_of")

        except Exception as e:
            log_event("supervisor_error", request_id, node="supervisor",
                      data={"error": str(e)}, level="error")
            intent = "general"
            intent_type = "conversational"
            risk = "low"
            needs_escalation = False
            is_continuation = False
            affirmation_of = None

        # Heuristic overrides (belt-and-suspenders)
        from identity.service import is_policy_or_info_query, is_action_request
        if is_policy_or_info_query(query, intent):
            intent = "policy_query"
            intent_type = "knowledge"
        elif is_action_request(query, intent) and intent == "general":
            q = query.lower()
            if "return" in q or "damage" in q:
                intent = "return" if "return" in q else "damaged_return"
            elif "refund" in q:
                intent = "refund"
            elif "cancel" in q:
                intent = "cancel"
            elif "track" in q or "where is" in q or "where's my" in q:
                intent = "track"
            intent_type = _extract_intent_type(intent)

        # Prevent spurious high-risk
        dangerous_keywords = ["fraud", "scam", "hack", "threat", "kill", "bomb", "abuse"]
        if risk == "high" and not any(k in query.lower() for k in dangerous_keywords):
            risk = "medium"

    # ── Decision contract ────────────────────────────────────────────────────
    requires_rag = (intent_type == "knowledge")
    requires_identity = (intent_type in ("transactional", "action"))
    requires_tool = (intent_type in ("transactional", "action"))

    tool_name: Optional[str] = None
    if intent in ("track", "order_status"):
        tool_name = "shopify_get_order"
    elif intent in ("return", "damaged_return"):
        tool_name = "shopify_initiate_return"
    elif intent == "cancel":
        tool_name = "shopify_cancel_order"
    elif intent == "refund":
        tool_name = "stripe_refund"
    elif intent_type == "knowledge":
        tool_name = "search_policy"

    response_mode = "conversational"
    if requires_identity and auth_level == "anonymous":
        response_mode = "challenge"

    # Carry forward active_intent for next turn
    sticky_intent: Optional[str] = None
    if intent_type in ("action", "transactional"):
        sticky_intent = intent
    elif is_continuation:
        sticky_intent = active_intent if active_intent != "none" else intent

    log_event("supervisor_completed", request_id, node="supervisor", data={
        "intent": intent,
        "intent_type": intent_type,
        "risk": risk,
        "requires_rag": requires_rag,
        "requires_identity": requires_identity,
        "requires_tool": requires_tool,
        "tool_name": tool_name,
        "response_mode": response_mode,
        "is_continuation": is_continuation,
        "affirmation_of": affirmation_of,
        "active_intent_next": sticky_intent,
    })

    return {
        "intent": intent,
        "intent_type": intent_type,
        "risk_level": risk,
        "needs_escalation": needs_escalation,
        "requires_rag": requires_rag,
        "requires_identity": requires_identity,
        "requires_tool": requires_tool,
        "tool_name": tool_name,
        "response_mode": response_mode,
        "is_continuation": is_continuation,
        "affirmation_of": affirmation_of,
        "active_intent": sticky_intent,
    }


def supervisor_with_rag_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run supervisor. If knowledge query → run RAG prefetch in parallel.
    For transactional, action, conversational → skip RAG (no wasted retrieval).
    """
    from orchestration.rag_prefetch import rag_prefetch_node
    from identity.service import is_policy_or_info_query

    query = get_last_user_message(state.get("messages", []))
    memory_context = state.get("memory_context") or {}
    active_intent = state.get("active_intent") or memory_context.get("active_intent") or ""

    # Affirmations continuing an action intent → definitely skip RAG
    should_rag = (
        not _is_affirmation(query)
        and is_policy_or_info_query(query)
        and active_intent not in ("return", "refund", "cancel", "track", "damaged_return", "order_status")
    )

    if should_rag:
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_sup = pool.submit(supervisor_node, state)
            fut_rag = pool.submit(rag_prefetch_node, state)
            sup_out = fut_sup.result() or {}
            rag_out = fut_rag.result() or {}
        merged = {}
        merged.update(sup_out)
        merged.update(rag_out)
        return merged
    else:
        sup_out = supervisor_node(state) or {}
        sup_out["prefetched_docs"] = []
        sup_out["prefetched_citations"] = []
        sup_out["rag_prefetched"] = True
        return sup_out