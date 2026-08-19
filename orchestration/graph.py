from langgraph.graph import StateGraph, END
from orchestration.state import AgentState
from security.guardrails import apply_guardrails
from orchestration.supervisor import supervisor_with_rag_node
from orchestration.planner import planner_node
from orchestration.execution import execution_engine_node
from orchestration.verifier import verifier_node
from orchestration.hitl import check_escalation
from orchestration.routing import after_supervisor_route
from identity.gate import identity_gate_node
from agents.qa import qa_node


def after_identity_route(state):
    if state.get("identity_blocked") and state.get("needs_escalation"):
        return "end"

    # Still collecting identity → speak challenge
    if state.get("identity_blocked") or (
        state.get("needs_identity") and state.get("identity_challenge")
    ):
        return "qa"

    memory = state.get("memory_context") or {}
    intent = (
        state.get("intent")
        or (state.get("current_plan") or {}).get("intent")
        or memory.get("issue_type")
        or memory.get("intent")
        or ""
    )
    intent = str(intent).lower().strip()

    auth = str(state.get("auth_level") or memory.get("auth_level") or "").lower()

    # Just identified on a contact-only turn — continue the return/refund case
    action_intents = ("return", "refund", "cancel", "replace", "replacement", "track")
    if auth in ("identified", "verified") and any(a in intent for a in action_intents):
        return "planner"

    # Fallback: if we have a resolved order and were in identity flow, still act
    if auth in ("identified", "verified") and (
        state.get("resolved_order_id") or memory.get("pending_order_id") or memory.get("active_order_id")
    ):
        return "planner"

    if any(a in intent for a in action_intents):
        return "planner"

    return "hitl_check"


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("guardrails", apply_guardrails)
    graph.add_node("supervisor", supervisor_with_rag_node)
    graph.add_node("identity_gate", identity_gate_node)
    graph.add_node("planner", planner_node)
    graph.add_node("executor", execution_engine_node)
    graph.add_node("verifier", verifier_node)
    graph.add_node("hitl_check", check_escalation)
    graph.add_node("qa", qa_node)

    graph.set_entry_point("guardrails")

    # Guardrails
    graph.add_conditional_edges(
        "guardrails",
        lambda s: "blocked" if s.get("blocked") else "supervisor",
        {
            "blocked": END,
            "supervisor": "supervisor",
        },
    )

    # Supervisor → Identity Gate
    graph.add_edge("supervisor", "identity_gate")

    # Identity Gate → challenge QA / planner / policy HITL / end
    graph.add_conditional_edges(
        "identity_gate",
        after_identity_route,
        {
            "qa": "qa",
            "planner": "planner",
            "hitl_check": "hitl_check",
            "end": END,
        },
    )

    # Action path
    graph.add_edge("planner", "executor")
    graph.add_edge("executor", "verifier")

    graph.add_conditional_edges(
        "verifier",
        lambda s: "escalate" if not s.get("verification_passed", True) else "hitl_check",
        {
            "escalate": END,
            "hitl_check": "hitl_check",
        },
    )

    graph.add_conditional_edges(
        "hitl_check",
        lambda s: "escalate" if s.get("needs_escalation") else "qa",
        {
            "escalate": END,
            "qa": "qa",
        },
    )

    graph.add_edge("qa", END)

    return graph.compile()


compiled_graph = build_graph()