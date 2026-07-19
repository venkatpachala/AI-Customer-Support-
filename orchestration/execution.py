from orchestration.state import AgentState
from tools.shopify import get_order_details, initiate_return
from tools.stripe import process_refund
from typing import Dict
import re
import traceback

def extract_order_id(text: str) -> str:
    """Extract order ID from user message"""
    match = re.search(r'#?(\d{4,})', text)
    return match.group(1) if match else "12345"

def execution_engine_node(state: AgentState) -> Dict:
    """
    Dynamic tool executor with error handling
    """
    plan = state.get("current_plan", {})
    tool_results = state.get("tool_results", {})
    messages = state.get("messages", [])
    
    # Safely get last user message
    last_query = ""
    if messages:
        last = messages[-1]
        last_query = last.content if hasattr(last, "content") else str(last)
    
    order_id = extract_order_id(last_query)
    steps = plan.get("steps") or []

    for step in steps:
        if not isinstance(step, dict):
            continue

        tool_name = step.get("tool")
        if not tool_name:
            continue

        try:
            if tool_name == "shopify_get_order":
                result = get_order_details(order_id)
                tool_results[tool_name] = {
                    "status": "success",
                    "data": result
                }
                print(f"Executed {tool_name} for order {order_id}")

            elif tool_name == "shopify_initiate_return":
                result = initiate_return(order_id, reason="damaged")
                tool_results[tool_name] = {
                    "status": "success",
                    "data": result
                }
                print(f"Executed {tool_name}")

            elif tool_name == "stripe_refund":
                result = process_refund(order_id, amount=500)
                tool_results[tool_name] = {
                    "status": "success",
                    "data": result
                }
                print(f"Executed {tool_name}")

            elif tool_name == "rag_search":
                tool_results[tool_name] = {
                    "status": "success",
                    "data": {"message": "Policy retrieved via RAG"}
                }

            else:
                tool_results[tool_name] = {
                    "status": "skipped",
                    "data": {"message": f"Unknown tool: {tool_name}"}
                }
                print(f"Unknown tool: {tool_name}")

        except Exception as e:
            error_msg = str(e)
            print(f"Error executing {tool_name}: {error_msg}")
            traceback.print_exc()
            
            tool_results[tool_name] = {
                "status": "error",
                "error": error_msg,
                "data": None
            }

    return {
        "tool_results": tool_results
    }