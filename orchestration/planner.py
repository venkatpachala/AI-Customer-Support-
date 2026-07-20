from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from orchestration.state import AgentState
from orchestration.plans import ExecutionPlan
from common.messages import get_last_user_message
from observability.logging import log_event
from typing import Dict
import uuid
import json
import re

llm = ChatOllama(
    model="qwen2.5:7b",
    base_url="http://127.0.0.1:11434",
    temperature=0
)

planner_prompt = ChatPromptTemplate.from_template(
    """You are an enterprise-grade planner for customer support.

{config_context}

Memory Context:
{memory_context}

User Query: {query}

Available tools:
- shopify_get_order
- shopify_initiate_return
- stripe_refund
- rag_search

Important memory rules:
- If active_order_id is already present, do not ask for order ID again.
- If photos_requested is true and photos_received is false, keep photos in missing_inputs.
- If case_status is escalated, create a minimal plan and avoid new tool actions.
- Reuse known details from memory.

Return ONLY valid JSON:
{{
  "plan_id": "plan_xxx",
  "intent": "return|refund|cancel|track|general",
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

    response = llm.invoke(
        planner_prompt.format(
            query=query,
            config_context=config_context,
            memory_context=memory_text
        )
    )
    content = response.content.strip()

    try:
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            content = json_match.group(0)
        plan_dict = json.loads(content)
        plan = ExecutionPlan(**plan_dict)
    except Exception as e:
        log_event("planner_parse_failed", request_id, node="planner", data={"error": str(e)}, level="error")
        plan = ExecutionPlan(
            plan_id=str(uuid.uuid4()),
            intent="general",
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

    log_event("planner_completed", request_id, node="planner", data={
        "plan_id": plan.plan_id,
        "intent": plan.intent,
        "steps": len(plan.steps),
        "missing_inputs": plan.missing_inputs,
        "confidence": plan.confidence
    })

    return {
        "current_plan": plan.dict(),
        "workflow_steps": [step.dict() for step in plan.steps],
        "needs_escalation": False
    }