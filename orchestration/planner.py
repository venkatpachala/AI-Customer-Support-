from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from orchestration.state import AgentState
from orchestration.plans import ExecutionPlan
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
    """You are a planner for Zepto customer support.

User Query: {query}

Available tools:
- shopify_get_order
- shopify_initiate_return
- stripe_refund
- rag_search

Create a realistic execution plan. Return ONLY valid JSON.

Example:
{{
  "plan_id": "plan_001",
  "intent": "return",
  "steps": [
    {{"step": 1, "description": "Fetch order details", "tool": "shopify_get_order", "required": true}},
    {{"step": 2, "description": "Check return eligibility", "tool": "rag_search", "required": true}},
    {{"step": 3, "description": "Initiate return", "tool": "shopify_initiate_return", "required": false}}
  ],
  "requires_human_approval": false,
  "confidence": 0.85,
  "estimated_steps": 3
}}

Query: {query}
"""
)

def planner_node(state: AgentState) -> Dict:
    query = get_last_user_message(state.get("messages", []))
    
    response = llm.invoke(planner_prompt.format(query=query))
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
            requires_human_approval=False,
            confidence=0.5,
            estimated_steps=1
        )
    
    print(f"Plan generated: {plan.plan_id} | Intent: {plan.intent} | Steps: {len(plan.steps)}")
    
    return {
        "current_plan": plan.dict(),
        "workflow_steps": [s.dict() for s in plan.steps]
    }