from typing import Annotated, List, Dict, Optional
from langgraph.graph import add_messages
from langchain_core.messages import BaseMessage

class AgentState(Dict):
    messages: Annotated[List[BaseMessage], add_messages]
    customer_id: Optional[str]
    customer_context: Dict
    current_plan: Optional[Dict]
    workflow_steps: List[Dict]
    tool_results: Dict
    confidence: float
    citations: List[Dict]
    memory_retrieved: List[str]
    risk_level: str
    needs_escalation: bool
    needs_escalation: bool
    escalation_reason: str
    risk_level: str
    tenant_id: str
    tenant_config: dict
    request_id: str