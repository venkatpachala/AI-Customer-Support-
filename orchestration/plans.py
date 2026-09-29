from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class PlanStep(BaseModel):
    step: int
    description: str
    tool: str
    required: bool = True
    depends_on: List[int] = Field(default_factory=list)
    condition: Optional[str] = None
    params: Optional[Dict[str, Any]] = None

class ApprovalRules(BaseModel):
    requires_human_approval: bool = False
    reason: Optional[str] = None

class ExecutionPlan(BaseModel):
    plan_id: str
    intent: str
    required_inputs: List[str] = Field(default_factory=list)
    missing_inputs: List[str] = Field(default_factory=list)
    steps: List[PlanStep] = Field(default_factory=list)
    approval_rules: ApprovalRules = Field(default_factory=ApprovalRules)
    fallback_steps: List[PlanStep] = Field(default_factory=list)
    replan_triggers: List[str] = Field(default_factory=list)
    confidence: float = 0.7
    estimated_steps: int = 0
    # Action intents name a durable workflow. read_tools are the only tools
    # the executor may call. Side effects stay inside WorkflowEngine.
    workflow: Optional[str] = None
    read_tools: List[str] = Field(default_factory=list)
    slots: Dict[str, Any] = Field(default_factory=dict)