from langgraph.graph import StateGraph, END
from orchestration.state import AgentState
from security.guardrails import apply_guardrails
from orchestration.supervisor import supervisor_node
from orchestration.planner import planner_node
from agents.qa import qa_node

def build_graph():
    graph = StateGraph(AgentState)
    
    graph.add_node("guardrails", lambda s: apply_guardrails(s))
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("planner", planner_node)
    graph.add_node("qa", qa_node)
    
    graph.set_entry_point("guardrails")
    graph.add_conditional_edges("guardrails", lambda s: "blocked" if s.get("blocked") else "supervisor")
    graph.add_edge("supervisor", "planner")
    graph.add_edge("planner", "qa")
    graph.add_edge("qa", END)
    
    return graph.compile()

compiled_graph = build_graph()