from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from orchestration.state import AgentState
from orchestration.plans import ExecutionPlan, PlanStep, ApprovalRules
from common.messages import get_last_user_message
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

User Query: {query}

Available tools:
- shopify_get_order
- shopify_initiate_return
- stripe_refund
- rag_search

Create a structured execution plan. Return ONLY valid JSON in this format:

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

Rules:
- Identify required vs missing inputs
- Add realistic step dependencies
- Use the tenant configuration for approval decisions
- Keep the plan minimal and executable
"""
)

def planner_node(state: AgentState) -> Dict:
    query = get_last_user_message(state.get("messages", []))
    
    # Load tenant configuration
    tenant_config = state.get("tenant_config") or {}
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

    response = llm.invoke(
        planner_prompt.format(
            query=query,
            config_context=config_context
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
        print(f"Planner parsing failed: {e}")
        plan = ExecutionPlan(
            plan_id=str(uuid.uuid4()),
            intent="general",
            steps=[],
            confidence=0.4,
            estimated_steps=0,
            replan_triggers=["parsing_failure"]
        )

    print(f"Plan generated: {plan.plan_id} | Intent: {plan.intent} | Steps: {len(plan.steps)} | Missing: {plan.missing_inputs}")

    return {
        "current_plan": plan.dict(),
        "workflow_steps": [step.dict() for step in plan.steps],
        "needs_escalation": plan.approval_rules.requires_human_approval
    }