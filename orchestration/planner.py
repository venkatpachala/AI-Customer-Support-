from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from orchestration.state import AgentState
from orchestration.plans import ExecutionPlan
from common.messages import get_last_user_message
from typing import Dict
import uuid

llm = ChatOllama(model="qwen2.5:7b", temperature=0)

planner_prompt = ChatPromptTemplate.from_template(
    """Create a detailed execution plan for customer support.

Query: {query}

Available tools: shopify_get_order, shopify_initiate_return, rag_search, stripe_refund

Return ONLY valid JSON:

{{
  "plan_id": "plan_xxx",
  "intent": "return|refund|track|general",
  "steps": [
    {{"step": 1, "description": "Fetch order details", "tool": "shopify_get_order", "required": true}}
  ],
  "requires_human_approval": false,
  "confidence": 0.85,
  "estimated_steps": 3
}}"""
)

def planner_node(state: AgentState) -> Dict:
    query = get_last_user_message(state.get("messages", []))
    
    response = llm.invoke(planner_prompt.format(query=query))
    
    try:
        import json
        plan_dict = json.loads(response.content)
        plan = ExecutionPlan(**plan_dict)
    except:
        plan = ExecutionPlan(
            plan_id=str(uuid.uuid4()),
            intent="general",
            steps=[],
            requires_human_approval=False,
            confidence=0.6,
            estimated_steps=1
        )
    
    print(f"Plan generated: {plan.plan_id} | Intent: {plan.intent} | Steps: {len(plan.steps)}")
    
    return {
        "current_plan": plan.dict(),
        "workflow_steps": [s.dict() for s in plan.steps]
    }