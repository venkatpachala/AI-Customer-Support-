import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from typing import Dict, Any, Set
from orchestration.state import AgentState
from tools.registry import TOOL_REGISTRY

def extract_order_id(text: str) -> str:
    match = re.search(r'(?:order\s*#?|#)?(\d{5,})', text, re.IGNORECASE)
    return match.group(1) if match else "12345"

def extract_amount(text: str) -> int:
    """Extract refund amount from user message"""
    match = re.search(r'(?:₹|rs\.?|inr)?\s*(\d{3,6})', text.lower().replace(",", ""))
    if match:
        return int(match.group(1))
    return 500

def run_tool_with_retries(tool_spec, params: Dict[str, Any]) -> Dict:
    last_error = None

    for attempt in range(1, tool_spec.max_retries + 2):
        try:
            print(f"  Attempt {attempt} for {tool_spec.name} (timeout={tool_spec.timeout}s)")

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(tool_spec.function, **params)
                result = future.result(timeout=tool_spec.timeout)

            return {
                "status": "success",
                "data": result,
                "attempts": attempt,
                "timeout": tool_spec.timeout,
                "idempotent": tool_spec.idempotent
            }

        except FuturesTimeoutError:
            last_error = f"Timeout after {tool_spec.timeout} seconds"
            print(f"  Timeout on attempt {attempt}")

        except Exception as e:
            last_error = str(e)
            print(f"  Failed attempt {attempt}: {e}")

        time.sleep(0.4 * attempt)

    return {
        "status": "error",
        "error": last_error,
        "attempts": tool_spec.max_retries + 1,
        "data": None
    }

def execution_engine_node(state: AgentState) -> Dict:
    plan = state.get("current_plan") or {}
    tool_results = state.get("tool_results") or {}
    messages = state.get("messages", [])

    last_query = ""
    if messages:
        last = messages[-1]
        last_query = last.content if hasattr(last, "content") else str(last)

    order_id = extract_order_id(last_query)
    amount = extract_amount(last_query)
    steps = plan.get("steps") or []
    missing_inputs = set(plan.get("missing_inputs") or [])

    print("\n=== Advanced Execution Engine ===")
    print(f"Order ID: {order_id} | Amount: ₹{amount}")
    print(f"Missing inputs: {missing_inputs}")

    completed_steps: Set[int] = set()
    remaining_steps = [s for s in steps if isinstance(s, dict)]

    while remaining_steps:
        ready_steps = []
        still_waiting = []

        for step in remaining_steps:
            depends_on = step.get("depends_on") or []
            if all(dep in completed_steps for dep in depends_on):
                ready_steps.append(step)
            else:
                still_waiting.append(step)

        if not ready_steps:
            for step in still_waiting:
                tool_name = step.get("tool")
                tool_results[tool_name] = {
                    "status": "skipped",
                    "reason": f"Unmet dependencies: {step.get('depends_on')}"
                }
            break

        print(f"Ready steps: {[s.get('tool') for s in ready_steps]}")

        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_step = {}

            for step in ready_steps:
                tool_name = step.get("tool")
                step_num = step.get("step")

                if "photos" in missing_inputs and tool_name in ["shopify_initiate_return", "stripe_refund"]:
                    tool_results[tool_name] = {
                        "status": "skipped",
                        "reason": "Missing required input: photos"
                    }
                    print(f"Skipped {tool_name} - missing photos")
                    completed_steps.add(step_num)
                    continue

                tool_spec = TOOL_REGISTRY.get(tool_name)
                if not tool_spec:
                    tool_results[tool_name] = {
                        "status": "error",
                        "error": f"Tool '{tool_name}' not registered"
                    }
                    completed_steps.add(step_num)
                    continue

                # Prepare parameters
                params = {"order_id": order_id}
                if tool_name == "shopify_initiate_return":
                    params["reason"] = "damaged"
                if tool_name == "stripe_refund":
                    params["amount"] = amount

                future = executor.submit(run_tool_with_retries, tool_spec, params)
                future_to_step[future] = step

            for future in as_completed(future_to_step):
                step = future_to_step[future]
                tool_name = step.get("tool")
                step_num = step.get("step")

                try:
                    result = future.result()
                    tool_results[tool_name] = result
                    if result["status"] == "success":
                        completed_steps.add(step_num)
                        print(f"Completed: {tool_name}")
                    else:
                        print(f"Failed: {tool_name}")
                except Exception as e:
                    tool_results[tool_name] = {"status": "error", "error": str(e)}

        remaining_steps = still_waiting

    print("=== Execution Finished ===\n")
    return {"tool_results": tool_results}