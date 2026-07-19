from langgraph.graph import StateGraph, END
from orchestration.state import AgentState
from security.guardrails import apply_guardrails
from orchestration.supervisor import supervisor_node
from orchestration.planner import planner_node
from orchestration.execution import execution_engine_node
from orchestration.hitl import check_escalation
from agents.qa import qa_node

from orchestration.verifier import verifier_node

def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("guardrails", lambda s: apply_guardrails(s))
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("planner", planner_node)
    graph.add_node("executor", execution_engine_node)
    graph.add_node("verifier", verifier_node)
    graph.add_node("hitl_check", check_escalation)
    graph.add_node("qa", qa_node)

    graph.set_entry_point("guardrails")

    graph.add_conditional_edges(
        "guardrails",
        lambda s: "blocked" if s.get("blocked") else "supervisor",
        {"blocked": END, "supervisor": "supervisor"}
    )

    graph.add_edge("supervisor", "planner")
    graph.add_edge("planner", "executor")
    graph.add_edge("executor", "verifier")

    # After verification
    graph.add_conditional_edges(
        "verifier",
        lambda s: "escalate" if not s.get("verification_passed", True) else "hitl_check",
        {
            "escalate": END,
            "hitl_check": "hitl_check"
        }
    )

    graph.add_conditional_edges(
        "hitl_check",
        lambda s: "escalate" if s.get("needs_escalation") else "qa",
        {
            "escalate": END,
            "qa": "qa"
        }
    )

    graph.add_edge("qa", END)

    return graph.compile()

compiled_graph = build_graph()