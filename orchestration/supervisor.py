from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from orchestration.state import AgentState
from common.messages import get_last_user_message
from observability.logging import log_event
from typing import Dict
import json
import re

llm = ChatOllama(
    model="qwen2.5:7b",
    base_url="http://127.0.0.1:11434",
    temperature=0
)

supervisor_prompt = ChatPromptTemplate.from_template(
    """You are a supervisor for Zepto customer support.

Classify the user query. Be conservative with risk.
Only mark risk as "high" for clear fraud, threat, or abuse.

Query: {query}

Return ONLY valid JSON:
{{
  "intent": "return|refund|cancel|track|general",
  "risk": "low|medium|high",
  "needs_escalation": false
}}
"""
)

def supervisor_node(state: AgentState) -> Dict:
    request_id = state.get("request_id", "unknown")
    log_event("supervisor_started", request_id, node="supervisor")

    query = get_last_user_message(state.get("messages", []))

    try:
        response = llm.invoke(supervisor_prompt.format(query=query))
        content = response.content.strip()

        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            content = json_match.group(0)

        data = json.loads(content)
        intent = data.get("intent", "general")
        risk = data.get("risk", "low")
        needs_escalation = data.get("needs_escalation", False)

        dangerous_keywords = ["fraud", "scam", "hack", "threat", "kill", "bomb", "abuse"]
        if risk == "high" and not any(k in query.lower() for k in dangerous_keywords):
            risk = "medium"

    except Exception as e:
        log_event("supervisor_error", request_id, node="supervisor", data={"error": str(e)}, level="error")
        intent = "general"
        risk = "low"
        needs_escalation = False

    log_event("supervisor_completed", request_id, node="supervisor", data={
        "intent": intent,
        "risk": risk
    })

    return {
        "risk_level": risk,
        "needs_escalation": needs_escalation
    }