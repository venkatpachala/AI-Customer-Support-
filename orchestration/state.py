from typing import Annotated, List, Dict, Optional, Any
from langgraph.graph import add_messages
from langchain_core.messages import BaseMessage


class AgentState(Dict):
    # ── Core messaging ──────────────────────────────────────────────────────
    messages: Annotated[List[BaseMessage], add_messages]

    # ── Customer & tenant ───────────────────────────────────────────────────
    customer_id: Optional[str]
    customer_context: Dict
    tenant_id: str
    tenant_config: dict
    request_id: str
    # Kept on the graph so /chat can start and resume a workflow.
    session_id: Optional[str]
    case_id: Optional[str]
    memory_context: Optional[Dict]
    verified: Optional[bool]
    verified_order_ids: Optional[List[str]]
    photos_received: Optional[bool]
    missing_photos: Optional[bool]
    tool_registry: Optional[Any]
    workflow_engine: Optional[Any]

    # ── Workflow / plan ──────────────────────────────────────────────────────
    current_plan: Optional[Dict]
    workflow_steps: List[Dict]
    tool_results: Dict
    confidence: float
    citations: List[Dict]
    memory_retrieved: List[str]

    # ── Risk & escalation ───────────────────────────────────────────────────
    risk_level: str
    needs_escalation: bool
    escalation_reason: str

    # ── RAG prefetch ─────────────────────────────────────────────────────────
    prefetched_docs: Optional[list]
    prefetched_citations: Optional[list]
    rag_prefetched: bool

    # ── Identity ─────────────────────────────────────────────────────────────
    needs_identity: bool
    auth_level: str
    identity_challenge: dict
    identity_result: dict
    customer_contact: str

    # ── Supervisor decision contract (Phase 3) ───────────────────────────────
    intent: Optional[str]               # return | refund | cancel | track | order_status | policy_query | general
    intent_type: Optional[str]          # knowledge | transactional | action | conversational
    requires_rag: bool
    requires_identity: bool
    requires_tool: bool
    tool_name: Optional[str]            # shopify_get_order | stripe_refund | ...
    response_mode: Optional[str]        # direct | challenge | conversational
    affirmation_of: Optional[str]       # when "yes/ok" continues a prior intent
    is_continuation: bool               # True when message continues previous turn's intent

    # ── Conversation memory (Phase 3) ─────────────────────────────────────────
    active_intent: Optional[str]        # sticky intent across turns: "damaged_return" | "order_status"
    active_case_type: Optional[str]     # type of ongoing case
    pending_action: Optional[str]       # next expected action if mid-flow
    last_tool_name: Optional[str]       # name of last executed tool
    last_tool_result: Optional[Dict]    # result of last executed tool
    conversation_turns: Optional[List[Dict]]  # [{role, text, intent}] last N turns
    detected_language: Optional[str]    # language detected from STT

    # ── Per-turn trace (Phase 3) ──────────────────────────────────────────────
    turn_trace: Optional[Dict[str, Any]]  # structured per-turn observability record

    # ── Durable workflow (P0-D) ──────────────────────────────────────────────
    # The planner may name a workflow. The executor starts it. Stripe stays
    # inside the engine, and these fields carry the snapshot to HITL and QA.
    policy_decision: Optional[Dict]
    workflow_run_id: Optional[str]
    workflow_name: Optional[str]
    workflow_status: Optional[str]
    workflow_waiting: Optional[str]  # input | approval | auth | None