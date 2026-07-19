from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from orchestration.state import AgentState
from common.messages import get_last_user_message
from typing import Dict

llm = ChatOllama(
    model="qwen2.5:7b",
    base_url="http://127.0.0.1:11434",
    temperature=0
)

supervisor_prompt = ChatPromptTemplate.from_template(
    """Classify the customer support query.

Query: {query}

Return ONLY valid JSON:
{{
  "intent": "return|refund|track|cancel|general",
  "risk": "low|medium|high",
  "needs_escalation": false
}}
"""
)

def supervisor_node(state: AgentState) -> Dict:
    query = get_last_user_message(state.get("messages", []))
    
    try:
        response = llm.invoke(supervisor_prompt.format(query=query))
        content = response.content.strip()
        
        risk = "medium"
        needs_escalation = False
        
        if "high" in content.lower():
            risk = "high"
        elif "low" in content.lower():
            risk = "low"
            
        if "true" in content.lower():
            needs_escalation = True
            
    except Exception as e:
        print(f"Supervisor error: {e}")
        risk = "medium"
        needs_escalation = False

    return {
        "risk_level": risk,
        "needs_escalation": needs_escalation
    }