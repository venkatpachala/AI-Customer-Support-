from langgraph.graph import StateGraph, END
from orchestration.state import AgentState
from security.guardrails import apply_guardrails
from orchestration.supervisor import supervisor_with_rag_node
from orchestration.planner import planner_node
from orchestration.execution import execution_engine_node
from orchestration.verifier import verifier_node
from orchestration.hitl import check_escalation
from orchestration.routing import after_supervisor_route
from agents.qa import qa_node


def build_graph():
    graph = StateGraph(AgentState)

    # Nodes
    graph.add_node("guardrails", apply_guardrails)
    graph.add_node("supervisor", supervisor_with_rag_node)  # supervisor + RAG in parallel inside node
    graph.add_node("planner", planner_node)
    graph.add_node("executor", execution_engine_node)
    graph.add_node("verifier", verifier_node)
    graph.add_node("hitl_check", check_escalation)
    graph.add_node("qa", qa_node)

    # Entry
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

    # Supervisor routing (policy fast path vs action path)
    graph.add_conditional_edges(
        "supervisor",
        after_supervisor_route,
        {
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

    # HITL → QA (single path, no join fan-in)
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