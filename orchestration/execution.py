import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, Set, Optional

from orchestration.planner import BANNED_EXECUTOR_TOOLS, READ_TOOL_ALLOWLIST, workflow_for_intent
from orchestration.state import AgentState
from tools.registry import TOOL_REGISTRY
from tools.base.context import ToolContext
from tools.base.response import ToolResponse
from tools.audit import (
    ToolAuditService,
    is_side_effecting,
    build_idempotency_key,
)
from observability.logging import log_event
from observability.metrics import TOOL_COUNT, NODE_LATENCY

audit_service = ToolAuditService()


def extract_order_id(text: str) -> Optional[str]:
    match = re.search(r'(?:order\s*#?|#)?(\d{5,})', text, re.IGNORECASE)
    return match.group(1) if match else None


def extract_amount(text: str) -> int:
    """
    Extract refund amount in major units (e.g. rupees).
    Avoid treating order IDs like #12345 as amounts.
    """
    text = text.lower().replace(",", "")

    patterns = [
        r'(?:refund|amount|pay|paid|worth|value)\s*(?:of|is|for)?\s*(?:₹|rs\.?|inr)?\s*(\d{3,6})',
        r'(?:₹|rs\.?|inr)\s*(\d{3,6})',
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))

    return 0


def to_minor_units(amount_major: int, currency: str = "inr") -> int:
    """
    Convert major units to Stripe minor units.
    INR/USD-style currencies use * 100.
    """
    currency = (currency or "inr").lower()
    if amount_major <= 0:
        return 0
    return int(amount_major * 100)


def build_tool_context(state: AgentState) -> ToolContext:
    return ToolContext(
        request_id=state.get("request_id", "unknown"),
        tenant_id=state.get("tenant_id", "zepto"),
        customer_id=state.get("customer_id"),
        case_id=state.get("case_id"),
        session_id=state.get("session_id"),
        extra={
            "risk_level": state.get("risk_level"),
            "memory_context": state.get("memory_context") or {},
        },
    )


def normalize_tool_result(result: Any) -> Dict[str, Any]:
    """
    Convert ToolResponse / dict into verifier-compatible structure.
    """
    if isinstance(result, ToolResponse):
        if result.success:
            return {
                "status": result.status if result.status in ["success", "requires_approval"] else "success",
                "data": result.data or {},
                "attempts": result.attempts,
                "latency_ms": result.latency_ms,
                "provider": result.provider,
                "operation": result.operation,
                "meta": result.meta or {},
            }
        return {
            "status": "error",
            "error": result.error_message or "Tool failed",
            "error_code": result.error_code,
            "retryable": result.retryable,
            "attempts": result.attempts,
            "latency_ms": result.latency_ms,
            "provider": result.provider,
            "operation": result.operation,
            "data": result.data,
        }

    if isinstance(result, dict):
        if "status" in result:
            return result
        return {
            "status": "success",
            "data": result,
        }

    return {
        "status": "success",
        "data": {"result": result},
    }


def build_tool_params(
    tool_name: str,
    *,
    order_id: Optional[str],
    amount_major: int,
    state: AgentState,
) -> Dict[str, Any]:
    """
    Build request payload for each tool.
    """
    params: Dict[str, Any] = {}

    if tool_name in ["shopify_get_order", "shopify_initiate_return", "stripe_refund"]:
        if order_id:
            params["order_id"] = order_id

    if tool_name == "shopify_initiate_return":
        params["reason"] = "damaged"

    if tool_name == "stripe_refund":
        amount_major_safe = amount_major if amount_major > 0 else 0
        params["amount"] = to_minor_units(amount_major_safe, "inr") if amount_major_safe > 0 else 0
        params["currency"] = "inr"
        params["reason"] = "requested_by_customer"

        tenant_config = state.get("tenant_config") or {}
        approval = tenant_config.get("approval", {})
        high_value_limit_major = int(approval.get("high_value_refund_limit", 2000))
        params["high_value_limit"] = to_minor_units(high_value_limit_major, "inr")
        params["require_approval_above_limit"] = True

        memory_context = state.get("memory_context") or {}
        payment_intent_id = memory_context.get("payment_intent_id")
        charge_id = memory_context.get("charge_id")
        if payment_intent_id:
            params["payment_intent_id"] = payment_intent_id
        if charge_id:
            params["charge_id"] = charge_id

    return params


def _registry_from(state: AgentState):
    return state.get("tool_registry") or TOOL_REGISTRY


def invoke_registry_tool(
    tool_name: str,
    params: Dict[str, Any],
    context: ToolContext,
    registry=None,
) -> Dict[str, Any]:
    """
    Invoke enterprise BaseTool from registry with:
    - audit logging
    - idempotent replay for side-effecting tools (refunds etc.)
    Retries/timeouts/auth remain inside BaseTool.
    """
    tool = (registry or TOOL_REGISTRY).get(tool_name)
    if tool is None:
        return {
            "status": "error",
            "error": f"Tool '{tool_name}' not registered",
            "error_code": "tool_not_registered",
        }

    provider = getattr(tool, "provider", None) or tool_name.split("_")[0]
    idem_key = None

    # Idempotency for side-effecting tools
    if is_side_effecting(tool_name):
        idem_key = build_idempotency_key(
            tool_name=tool_name,
            params=params,
            tenant_id=context.tenant_id or "",
            customer_id=context.customer_id or "",
            case_id=context.case_id or "",
        )
        prior = audit_service.get_by_idempotency_key(idem_key)
        if prior is not None and prior.result_json:
            cached = dict(prior.result_json)
            cached["idempotent_replay"] = True
            cached["tool_call_id"] = prior.tool_call_id
            cached["idempotency_key"] = idem_key
            print(f" ide mpotent replay for {tool_name} key={idem_key[:12]}...")
            return cached

    tool_call_id = audit_service.start(
        tool_name=tool_name,
        params=params,
        request_id=context.request_id,
        session_id=context.session_id,
        case_id=context.case_id,
        tenant_id=context.tenant_id,
        customer_id=context.customer_id,
        provider=provider,
        operation=tool_name,
        idempotency_key=idem_key,
    )

    t0 = time.time()
    try:
        # New SDK style
        if hasattr(tool, "execute"):
            raw = tool.execute(params, context)
            result = normalize_tool_result(raw)
        # Backward compatibility for old-style specs
        elif callable(tool):
            try:
                data = tool(params)
                result = data if isinstance(data, dict) and "status" in data else {
                    "status": "success",
                    "data": data if isinstance(data, dict) else {"result": data},
                    "attempts": 1,
                }
            except Exception as e:
                result = {
                    "status": "error",
                    "error": str(e),
                    "error_code": "legacy_tool_error",
                }
        elif hasattr(tool, "function"):
            try:
                data = tool.function(**params)
                result = {
                    "status": "success",
                    "data": data,
                    "attempts": 1,
                }
            except Exception as e:
                result = {
                    "status": "error",
                    "error": str(e),
                    "error_code": "legacy_tool_error",
                }
        else:
            result = {
                "status": "error",
                "error": f"Unsupported tool object for '{tool_name}'",
                "error_code": "unsupported_tool",
            }

        latency_ms = (time.time() - t0) * 1000.0
        status = result.get("status", "success")
        if status not in ("success", "error", "skipped", "requires_approval"):
            status = "success"

        audit_service.finish(
            tool_call_id,
            status="success" if status in ("success", "requires_approval") else status,
            result=result,
            error=result.get("error"),
            error_code=result.get("error_code"),
            latency_ms=latency_ms,
            attempts=int(result.get("attempts") or 1),
        )

        result["tool_call_id"] = tool_call_id
        if idem_key:
            result["idempotency_key"] = idem_key
        if "latency_ms" not in result:
            result["latency_ms"] = latency_ms
        return result

    except Exception as e:
        latency_ms = (time.time() - t0) * 1000.0
        err = {
            "status": "error",
            "error": str(e),
            "error_code": "executor_invoke_error",
            "tool_call_id": tool_call_id,
            "idempotency_key": idem_key,
            "latency_ms": latency_ms,
        }
        audit_service.finish(
            tool_call_id,
            status="error",
            result=err,
            error=str(e),
            error_code="executor_invoke_error",
            latency_ms=latency_ms,
        )
        return err


def _workflow_name_from_plan(state: AgentState, plan: Dict[str, Any]) -> Optional[str]:
    named = (plan.get("workflow") or "").strip()
    if named:
        return named
    return workflow_for_intent(plan.get("intent") or state.get("intent"))


def _workflow_slots(
    state: AgentState,
    plan: Dict[str, Any],
    *,
    order_id: Optional[str],
    amount_major: int,
    tool_results: Dict[str, Any],
) -> Dict[str, Any]:
    memory = state.get("memory_context") or {}
    slots = dict(plan.get("slots") or {})
    if order_id:
        slots["order_id"] = str(order_id)
    if amount_major and amount_major > 0:
        slots["amount"] = int(amount_major)
    elif slots.get("amount") in (0, "0", None, ""):
        slots.pop("amount", None)
    if memory.get("photos_received") or state.get("photos_received"):
        slots["photos_received"] = True
    else:
        slots["photos_received"] = bool(slots.get("photos_received"))
    order_result = tool_results.get("shopify_get_order")
    data = order_result.get("data") if isinstance(order_result, dict) else None
    if isinstance(data, dict):
        if data.get("status") or data.get("fulfillment_status"):
            slots["order_status"] = data.get("status") or data.get("fulfillment_status")
        total = data.get("total") or data.get("current_total_price")
        if total and not slots.get("amount"):
            try:
                slots["amount"] = int(float(total))
            except (TypeError, ValueError):
                pass
    return slots


def _stored_workflow(state: AgentState) -> tuple[Optional[str], Optional[str]]:
    memory = state.get("memory_context") or {}
    summary = memory.get("tool_results_summary") or {}
    nested = summary.get("workflow") if isinstance(summary.get("workflow"), dict) else {}
    run_id = (
        state.get("workflow_run_id")
        or summary.get("workflow_run_id")
        or nested.get("workflow_run_id")
    )
    status = (
        state.get("workflow_status")
        or summary.get("workflow_status")
        or nested.get("workflow_status")
    )
    return (str(run_id) if run_id else None, str(status) if status else None)


def _waiting_kind(status: Optional[str]) -> Optional[str]:
    return {
        "waiting_input": "input",
        "waiting_approval": "approval",
        "waiting_auth": "auth",
    }.get(status or "")


def _run_durable_workflow(
    state: AgentState,
    plan: Dict[str, Any],
    tool_results: Dict[str, Any],
    *,
    order_id: Optional[str],
    amount_major: int,
) -> Dict[str, Any]:
    """Start or resume the plan's workflow. Never calls Stripe from this node."""
    from workflows import WorkflowEngine
    from workflows.context import WorkflowContext

    workflow_name = _workflow_name_from_plan(state, plan)
    if not workflow_name:
        return {}

    request_id = state.get("request_id", "unknown")
    case_id = state.get("case_id") or (state.get("memory_context") or {}).get("case_id")
    if not case_id:
        log_event(
            "workflow_skipped",
            request_id,
            node="executor",
            data={"reason": "missing_case_id", "workflow": workflow_name},
            level="warning",
        )
        return {
            "workflow_name": workflow_name,
            "workflow_status": "failed",
            "workflow_error": "case_id is required",
        }

    slots = _workflow_slots(
        state,
        plan,
        order_id=order_id,
        amount_major=amount_major,
        tool_results=tool_results,
    )
    memory = state.get("memory_context") or {}
    from identity.ownership import case_auth

    stored_level, _orders, checked = case_auth(str(case_id))
    if checked:
        auth_level = stored_level
    else:
        auth_level = state.get("auth_level") or memory.get("auth_level") or "anonymous"
    engine = state.get("workflow_engine") or WorkflowEngine()
    ctx = WorkflowContext(
        tenant_id=state.get("tenant_id") or "zepto",
        case_id=str(case_id),
        customer_id=str(state.get("customer_id") or memory.get("customer_id") or "customer"),
        auth_level=str(auth_level),
        conversation_id=state.get("session_id") or memory.get("session_id"),
        slots=slots,
        tool_registry=state.get("tool_registry"),
    )
    stored_run_id, stored_status = _stored_workflow(state)
    try:
        if stored_run_id and str(stored_status or "").startswith("waiting"):
            view = engine.resume(stored_run_id, slots=slots)
        else:
            view = engine.start(workflow_name, ctx)
            if str(view.status or "").startswith("waiting"):
                # start() returns an existing paused run without applying new slots.
                view = engine.resume(view.run_id, slots=slots)
    except Exception as exc:
        log_event(
            "workflow_failed",
            request_id,
            node="executor",
            data={"error": str(exc), "workflow": workflow_name},
            level="error",
        )
        return {
            "workflow_name": workflow_name,
            "workflow_status": "failed",
            "workflow_error": str(exc),
        }

    output = dict(view.output or {})
    policy = output.get("policy") if isinstance(output.get("policy"), dict) else None
    requires = list(output.get("requires_inputs") or [])
    if not requires and policy:
        requires = list(policy.get("requires_inputs") or [])
    waiting = _waiting_kind(view.status)
    missing_photos = waiting == "input" and "photos" in requires
    log_event("workflow_finished", request_id, node="executor", data={
        "workflow": view.workflow_name,
        "run_id": view.run_id,
        "status": view.status,
        "deny_code": None if policy is None else policy.get("deny_code"),
    })
    tool_results["workflow"] = {
        "status": view.status,
        "workflow_run_id": view.run_id,
        "workflow_status": view.status,
        "workflow_name": view.workflow_name,
        "redirected_to_workflow": True,
    }
    payload = {
        "workflow_run_id": view.run_id,
        "workflow_name": view.workflow_name,
        "workflow_status": view.status,
        "workflow_waiting": waiting,
        "policy_decision": policy,
        "missing_photos": missing_photos,
    }
    if requires and view.status == "waiting_input":
        payload["missing_inputs"] = requires
    return payload


def execution_engine_node(state: AgentState) -> Dict:
    request_id = state.get("request_id", "unknown")
    start_time = time.time()

    plan = state.get("current_plan") or {}
    tool_results: Dict[str, Any] = state.get("tool_results") or {}
    messages = state.get("messages", [])
    memory_context = state.get("memory_context") or {}

    last_query = ""
    if messages:
        last = messages[-1]
        last_query = last.content if hasattr(last, "content") else str(last)

    order_id = memory_context.get("active_order_id") or extract_order_id(last_query)
    amount_major = extract_amount(last_query)

    steps = plan.get("steps") or []
    missing_inputs = set(plan.get("missing_inputs") or memory_context.get("missing_inputs") or [])
    already_executed = set(memory_context.get("tools_executed") or [])

    context = build_tool_context(state)
    registry = _registry_from(state)
    workflow_name = _workflow_name_from_plan(state, plan)

    log_event("executor_started", request_id, node="executor", data={
        "order_id": order_id,
        "amount": amount_major,
        "missing_inputs": list(missing_inputs),
        "already_executed": list(already_executed),
    })

    print("\n=== Enterprise Execution Engine ===")
    print(f"Order ID: {order_id} | Amount: ₹{amount_major}")
    print(f"Missing inputs: {missing_inputs}")
    print(f"Already executed: {already_executed}")

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
                if not tool_name:
                    continue
                tool_results[tool_name] = {
                    "status": "skipped",
                    "reason": f"Unmet dependencies: {step.get('depends_on')}",
                }
                try:
                    TOOL_COUNT.labels(tool_name=tool_name, status="skipped").inc()
                except Exception:
                    pass
            break

        print(f"Ready steps: {[s.get('tool') for s in ready_steps]}")

        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_step = {}

            for step in ready_steps:
                tool_name = step.get("tool")
                step_num = step.get("step")

                if not tool_name:
                    continue

                # Money movement and other writes belong to the workflow engine.
                if tool_name in BANNED_EXECUTOR_TOOLS or (
                    workflow_name and tool_name not in READ_TOOL_ALLOWLIST
                ):
                    tool_results[tool_name] = {
                        "status": "skipped",
                        "reason": "redirected_to_workflow",
                    }
                    log_event(
                        "tool_redirected_to_workflow",
                        request_id,
                        node="executor",
                        data={"tool": tool_name, "workflow": workflow_name},
                    )
                    try:
                        TOOL_COUNT.labels(tool_name=tool_name, status="skipped").inc()
                    except Exception:
                        pass
                    if isinstance(step_num, int):
                        completed_steps.add(step_num)
                    print(f"Redirected {tool_name} to workflow {workflow_name}")
                    continue

                # Skip idempotent read tools already executed in this case
                if tool_name in already_executed and tool_name in [
                    "shopify_get_order",
                    "rag_search",
                    "stripe_get_payment_intent",
                    "stripe_get_refund",
                ]:
                    tool_results[tool_name] = {
                        "status": "skipped",
                        "reason": "Already executed in this case",
                    }
                    try:
                        TOOL_COUNT.labels(tool_name=tool_name, status="skipped").inc()
                    except Exception:
                        pass
                    if isinstance(step_num, int):
                        completed_steps.add(step_num)
                    print(f"Skipped {tool_name} - already executed")
                    continue

                # Skip return/refund tools if photos still missing
                if "photos" in missing_inputs and tool_name in [
                    "shopify_initiate_return",
                    "stripe_refund",
                ]:
                    tool_results[tool_name] = {
                        "status": "skipped",
                        "reason": "Missing required input: photos",
                    }
                    try:
                        TOOL_COUNT.labels(tool_name=tool_name, status="skipped").inc()
                    except Exception:
                        pass
                    if isinstance(step_num, int):
                        completed_steps.add(step_num)
                    print(f"Skipped {tool_name} - missing photos")
                    continue

                # Need order_id for order-dependent tools
                if tool_name in [
                    "shopify_get_order",
                    "shopify_initiate_return",
                    "stripe_refund",
                ] and not order_id:
                    tool_results[tool_name] = {
                        "status": "skipped",
                        "reason": "Missing required input: order_id",
                    }
                    try:
                        TOOL_COUNT.labels(tool_name=tool_name, status="skipped").inc()
                    except Exception:
                        pass
                    if isinstance(step_num, int):
                        completed_steps.add(step_num)
                    print(f"Skipped {tool_name} - missing order_id")
                    continue

                if registry.get(tool_name) is None:
                    tool_results[tool_name] = {
                        "status": "error",
                        "error": f"Tool '{tool_name}' not registered",
                        "error_code": "tool_not_registered",
                    }
                    try:
                        TOOL_COUNT.labels(tool_name=tool_name, status="error").inc()
                    except Exception:
                        pass
                    if isinstance(step_num, int):
                        completed_steps.add(step_num)
                    continue

                params = build_tool_params(
                    tool_name,
                    order_id=order_id,
                    amount_major=amount_major,
                    state=state,
                )

                # The executor never calls Stripe or any other write, even if a plan names one.
                if tool_name not in {"shopify_get_order", "shopify_identify_customer", "health"}:
                    reason = (
                        "redirected_to_workflow"
                        if tool_name in BANNED_EXECUTOR_TOOLS
                        else "not_in_executor_allowlist"
                    )
                    tool_results[tool_name] = {"status": "skipped", "reason": reason}
                    log_event(
                        "tool_redirected_to_workflow",
                        request_id,
                        node="executor",
                        data={"tool": tool_name, "workflow": workflow_name, "reason": reason},
                    )
                    if isinstance(step_num, int):
                        completed_steps.add(step_num)
                    continue

                print(f"Invoking {tool_name} with params={params}")
                future = executor.submit(
                    invoke_registry_tool, tool_name, params, context, registry
                )
                future_to_step[future] = step

            for future in as_completed(future_to_step):
                step = future_to_step[future]
                tool_name = step.get("tool")
                step_num = step.get("step")

                try:
                    result = future.result()
                    tool_results[tool_name] = result
                    status = result.get("status", "unknown")

                    try:
                        TOOL_COUNT.labels(tool_name=tool_name, status=status).inc()
                    except Exception:
                        pass

                    if status in ["success", "requires_approval", "skipped"]:
                        if isinstance(step_num, int):
                            completed_steps.add(step_num)
                        replay = " (idempotent_replay)" if result.get("idempotent_replay") else ""
                        print(f"Completed: {tool_name} [{status}]{replay}")
                    else:
                        print(f"Failed: {tool_name} [{status}]")

                except Exception as e:
                    tool_results[tool_name] = {
                        "status": "error",
                        "error": str(e),
                        "error_code": "executor_invoke_error",
                    }
                    try:
                        TOOL_COUNT.labels(tool_name=tool_name, status="error").inc()
                    except Exception:
                        pass
                    print(f"Failed: {tool_name} [exception]")

        remaining_steps = still_waiting

    duration = time.time() - start_time
    try:
        NODE_LATENCY.labels(node="executor").observe(duration)
    except Exception:
        pass

    log_event("executor_completed", request_id, node="executor", data={
        "tools_executed": list(tool_results.keys()),
        "tool_statuses": {k: v.get("status") for k, v in tool_results.items()},
        "tool_call_ids": {
            k: v.get("tool_call_id")
            for k, v in tool_results.items()
            if isinstance(v, dict) and v.get("tool_call_id")
        },
        "order_id": order_id,
        "duration": round(duration, 3),
    })

    workflow_state = _run_durable_workflow(
        state,
        plan,
        tool_results,
        order_id=order_id,
        amount_major=amount_major,
    )

    print("=== Execution Finished ===\n")
    result = {
        "tool_results": tool_results,
        "resolved_order_id": order_id,
    }
    result.update(workflow_state)
    return result