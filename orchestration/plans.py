from pydantic import BaseModel
from typing import List, Optional

class PlanStep(BaseModel):
    step: int
    description: str
    tool: str
    required: bool = True
    params: Optional[dict] = None

class ExecutionPlan(BaseModel):
    plan_id: str
    intent: str
    steps: List[PlanStep]
    requires_human_approval: bool = False
    confidence: float = 0.7
    estimated_steps: int=3