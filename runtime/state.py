from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class VoiceState(TypedDict, total=False):
    call_id: str
    turn_id: int
    language: str
    detected_languages: List[str]
    interrupted: bool
    sentiment: str


class AgentStateV2(TypedDict, total=False):
    """
    Compatibility + extension surface for R2.
    Phase 0: only documents fields; graph can keep using orchestration.state.AgentState.
    """
    # identity / tenancy
    tenant_id: str
    customer_id: str
    session_id: str
    case_id: str
    request_id: str
    channel: str
    auth_level: str
    verified: bool
    verified_order_ids: List[str]

    # conversation
    messages: list
    intent: str
    risk_level: str
    language: str

    # memory / rag / plan
    memory_context: Dict[str, Any]
    retrieved_docs: list
    current_plan: Dict[str, Any]

    # tools / verification / hitl
    tool_results: Dict[str, Any]
    verification_passed: bool
    needs_escalation: bool
    escalation_reason: str
    blocked: bool

    # outputs
    citations: List[str]
    confidence: float
    missing_inputs: List[str]
    resolved_order_id: str

    # reserved for voice (Phase 1+)
    voice: VoiceState