from orchestration.state import AgentState
from tools.shopify import get_order_details, initiate_return
from tools.stripe import process_refund
from typing import Dict

def execution_engine_node(state: AgentState) -> Dict:
    plan = state.get("current_plan", {})
    tool_results = state.get("tool_results", {})
    
    steps = plan.get("steps") or []
    
    for step in steps:
        if not isinstance(step, dict):
            continue
        
        tool_name = step.get("tool")
        params = step.get("params") or {}
        
        if tool_name == "shopify_get_order":
            order_id = params.get("order_id") or "12345"
            result = get_order_details(order_id)
            tool_results[tool_name] = result
            print(f"✅ Executed {tool_name}")
        
        elif tool_name == "shopify_initiate_return":
            order_id = params.get("order_id") or "12345"
            reason = params.get("reason", "damaged")
            result = initiate_return(order_id, reason)
            tool_results[tool_name] = result
            print(f"✅ Executed {tool_name}")
        
        elif tool_name == "stripe_refund":
            order_id = params.get("order_id") or "12345"
            amount = params.get("amount", 500)
            result = process_refund(order_id, amount)
            tool_results[tool_name] = result
            print(f"✅ Executed {tool_name}")
    
    return {"tool_results": tool_results}