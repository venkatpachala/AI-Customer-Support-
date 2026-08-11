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


def after_identity_route(state: AgentState) -> str:
    """
    If identity is required and not satisfied, go straight to QA
    to ask for order_id/contact or report mismatch.
    Otherwise continue normal planner/HITL routing.
    """
    if state.get("needs_identity"):
        return "qa"
    return after_supervisor_route(state)


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

    # Identity Gate → QA challenge OR normal route
    graph.add_conditional_edges(
        "identity_gate",
        after_identity_route,
        {
            "qa": "qa",                 # ask for ownership details / mismatch
            "planner": "planner",       # action path
            "hitl_check": "hitl_check", # policy fast path
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