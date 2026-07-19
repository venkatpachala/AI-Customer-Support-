from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from orchestration.state import AgentState
from common.messages import get_last_user_message

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

prompt = ChatPromptTemplate.from_template(
    """Classify this customer query for support routing.
Query: {query}

Respond with JSON only: {{"intent": "...", "risk": "low/medium/high", "needs_escalation": true/false}}"""
)

def supervisor_node(state: AgentState):
    query = get_last_user_message(state["messages"])
    response = llm.invoke(prompt.format(query=query))
    return {
        "risk_level": "medium",
        "needs_escalation": False
    }