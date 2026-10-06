from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from orchestration.state import AgentState
from orchestration.plans import ExecutionPlan, PlanStep
from common.messages import get_last_user_message
from observability.logging import log_event
from typing import Dict
import uuid
import json
import re

from common.llm import get_planner_llm
llm = get_planner_llm()

# The model may still emit these. The executor must not call them.
BANNED_EXECUTOR_TOOLS = frozenset({
    "stripe_create_refund",
    "stripe_refund",
    "shopify_initiate_return",
    "shopify_cancel_order",
    "gmail_send_email",
    "gmail_send_escalation",
})

READ_TOOL_ALLOWLIST = frozenset({
    "shopify_get_order",
    "shopify_identify_customer",
    "health",
    "rag_search",
    "stripe_get_payment_intent",
    "stripe_get_refund",
})

_KNOWLEDGE_INTENTS = frozenset({
    "general",
    "policy",
    "policy_query",
    "faq",
    "greeting",
    "smalltalk",
    "conversational",
    "knowledge",
})

_INTENT_WORKFLOW = {
    "refund": "refund",
    "return": "return_damaged",
    "damaged_return": "return_damaged",
    "damage": "return_damaged",
    "cancel": "cancel",
    "replacement": "return_damaged",
    "replace": "return_damaged",
    "order_status": "order_status",
    "track": "order_status",
    "tracking": "order_status",
}


def workflow_for_intent(intent: str | None) -> str | None:
    key = (intent or "").lower().strip()
    if key in _KNOWLEDGE_INTENTS:
        return None
    return _INTENT_WORKFLOW.get(key)


def _infer_reason(query: str, memory: Dict) -> str | None:
    blob = f"{query} {memory.get('issue_type') or ''}".lower()
    if any(token in blob for token in ("preference", "changed my mind", "don't want", "do not want")):
        return "preference"
    if "missing" in blob:
        return "missing_item"
    if any(token in blob for token in ("damag", "broken", "torn", "leak")):
        return "damaged"
    return None


def _fill_slots(plan: ExecutionPlan, query: str, memory: Dict) -> Dict:
    slots = dict(plan.slots or {})
    order_id = memory.get("active_order_id") or slots.get("order_id")
    if not order_id:
        match = re.search(r"(?:order\s*#?|#)?(\d{5,})", query or "", re.IGNORECASE)
        order_id = match.group(1) if match else None
    if order_id:
        slots["order_id"] = str(order_id)

    amount = slots.get("amount")
    if not amount:
        text = (query or "").lower().replace(",", "")
        found = re.search(
            r"(?:refund|amount|pay|paid|worth|value)\s*(?:of|is|for)?\s*(?:₹|rs\.?|inr)?\s*(\d{3,6})",
            text,
        )
        if not found:
            found = re.search(r"(?:₹|rs\.?|inr)\s*(\d{3,6})", text)
        if found:
            amount = int(found.group(1))
    if amount:
        try:
            amount_int = int(float(amount))
        except (TypeError, ValueError):
            amount_int = 0
        if amount_int > 0:
            slots["amount"] = amount_int
        else:
            slots.pop("amount", None)

    if not slots.get("reason"):
        reason = _infer_reason(query, memory)
        if reason:
            slots["reason"] = reason

    if memory.get("photos_received"):
        slots["photos_received"] = True
    elif "photos_received" not in slots:
        slots["photos_received"] = False
    else:
        slots["photos_received"] = bool(slots.get("photos_received"))
    return slots


def normalize_action_plan(
    plan: ExecutionPlan,
    *,
    query: str,
    memory: Dict,
    state_intent: str | None = None,
) -> ExecutionPlan:
    """Attach the durable workflow and drop side-effecting tool steps.

    FAQ and policy intents stay on the old plan shape and do not start a refund.
    """
    supervisor_intent = (state_intent or "").lower().strip()
    if supervisor_intent in {"policy_query", "knowledge", "faq", "policy"}:
        workflow = None
    else:
        workflow = workflow_for_intent(plan.intent) or workflow_for_intent(supervisor_intent)

    kept_steps = []
    for step in plan.steps or []:
        if (step.tool or "") in BANNED_EXECUTOR_TOOLS:
            continue
        kept_steps.append(step)

    read_tools = [
        name for name in (plan.read_tools or [])
        if name in READ_TOOL_ALLOWLIST and name not in BANNED_EXECUTOR_TOOLS
    ]
    if workflow:
        if "shopify_get_order" not in read_tools:
            read_tools.insert(0, "shopify_get_order")
        if not any(step.tool == "shopify_get_order" for step in kept_steps):
            kept_steps.insert(
                0,
                PlanStep(
                    step=1,
                    description="Fetch order details",
                    tool="shopify_get_order",
                    required=True,
                    depends_on=[],
                ),
            )

    plan.workflow = workflow
    plan.read_tools = read_tools
    plan.steps = kept_steps
    plan.estimated_steps = len(kept_steps)
    plan.slots = _fill_slots(plan, query, memory or {})
    return plan

planner_prompt = ChatPromptTemplate.from_template(
    """You are an enterprise-grade planner for customer support.

{config_context}

Memory Context:
{memory_context}

User Query: {query}

Available read tools:
- shopify_get_order
- shopify_identify_customer
- health
- rag_search

Side-effecting tools (stripe_refund, stripe_create_refund, shopify_initiate_return) are not yours to call.
For refund, return, cancel, replacement, and order_status, set "workflow" and put only read tools in "steps".

Important memory rules:
- If active_order_id is already present, do not ask for order ID again.
- If photos_requested is true and photos_received is false, keep photos in missing_inputs.
- If case_status is escalated, create a minimal plan and avoid new tool actions.
- Reuse known details from memory.

Return ONLY valid JSON:
{{
  "plan_id": "plan_xxx",
  "intent": "return|refund|cancel|track|order_status|general",
  "workflow": "refund|return_damaged|cancel|order_status|null",
  "slots": {{
    "order_id": null,
    "amount": null,
    "reason": null,
    "photos_received": false
  }},
  "read_tools": ["shopify_get_order"],
  "required_inputs": ["order_id", "photos"],
  "missing_inputs": ["photos"],
  "steps": [
    {{
      "step": 1,
      "description": "Fetch order details",
      "tool": "shopify_get_order",
      "required": true,
      "depends_on": [],
      "condition": null
    }}
  ],
  "approval_rules": {{
    "requires_human_approval": false,
    "reason": null
  }},
  "fallback_steps": [],
  "replan_triggers": ["tool_failure", "missing_critical_input"],
  "confidence": 0.85,
  "estimated_steps": 3
}}
"""
)

def planner_node(state: AgentState) -> Dict:
    request_id = state.get("request_id", "unknown")
    log_event("planner_started", request_id, node="planner")

    query = get_last_user_message(state.get("messages", []))
    tenant_config = state.get("tenant_config") or {}
    memory_context = state.get("memory_context") or {}

    approval = tenant_config.get("approval", {})
    brand = tenant_config.get("brand", {})

    require_photos = approval.get("require_photos_for_return", True)
    auto_approve_limit = approval.get("refund_auto_approve_limit", 500)
    high_value_limit = approval.get("high_value_refund_limit", 2000)
    brand_name = brand.get("brand_name", "the company")

    config_context = f"""Tenant Configuration for {brand_name}:
- Require photos for returns: {require_photos}
- Auto-approve refund limit: ₹{auto_approve_limit}
- High value refund limit: ₹{high_value_limit}
"""

    memory_text = f"""
- session_id: {memory_context.get('session_id')}
- case_id: {memory_context.get('case_id')}
- active_order_id: {memory_context.get('active_order_id')}
- issue_type: {memory_context.get('issue_type')}
- case_status: {memory_context.get('case_status')}
- missing_inputs: {memory_context.get('missing_inputs')}
- photos_requested: {memory_context.get('photos_requested')}
- photos_received: {memory_context.get('photos_received')}
- tools_executed: {memory_context.get('tools_executed')}
"""

    try:
        response = llm.invoke(
            planner_prompt.format(
                query=query,
                config_context=config_context,
                memory_context=memory_text
            )
        )
        content = response.content.strip()
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            content = json_match.group(0)
        plan_dict = json.loads(content)
        plan = ExecutionPlan(**plan_dict)
    except Exception as e:
        # The supervisor intent still starts the workflow when the planner model is down.
        log_event("planner_parse_failed", request_id, node="planner", data={"error": str(e)}, level="error")
        plan = ExecutionPlan(
            plan_id=str(uuid.uuid4()),
            intent=str(state.get("intent") or "general"),
            steps=[],
            confidence=0.4,
            estimated_steps=0,
            replan_triggers=["parsing_failure"]
        )

    # Hard memory overrides for reliability
    missing_inputs = list(plan.missing_inputs or [])
    active_order_id = memory_context.get("active_order_id")
    photos_requested = memory_context.get("photos_requested", False)
    photos_received = memory_context.get("photos_received", False)

    if active_order_id and "order_id" in missing_inputs:
        missing_inputs = [m for m in missing_inputs if m != "order_id"]

    if photos_requested and not photos_received and "photos" not in missing_inputs:
        missing_inputs.append("photos")

    if photos_received and "photos" in missing_inputs:
        missing_inputs = [m for m in missing_inputs if m != "photos"]

    plan.missing_inputs = missing_inputs
    plan = normalize_action_plan(
        plan,
        query=query,
        memory=memory_context,
        state_intent=state.get("intent"),
    )

    log_event("planner_completed", request_id, node="planner", data={
        "plan_id": plan.plan_id,
        "intent": plan.intent,
        "steps": len(plan.steps),
        "missing_inputs": plan.missing_inputs,
        "workflow": plan.workflow,
        "confidence": plan.confidence
    })

    plan_payload = plan.model_dump() if hasattr(plan, "model_dump") else plan.dict()
    return {
        "current_plan": plan_payload,
        "workflow_steps": [step.model_dump() if hasattr(step, "model_dump") else step.dict() for step in plan.steps],
        "workflow_name": plan.workflow,
        "needs_escalation": False,
    }
