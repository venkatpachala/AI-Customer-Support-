"""
runtime/models.py — Canonical SupportRequest, SupportIntent, SupportAction, SupportResponse.

These types are the shared contract between Chat, Voice, and any future channel.
Both channels produce a SupportRequest; both consume a SupportResponse.
Neither Chat nor Voice should contain channel-specific business logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# SupportRequest — unified input contract for all channels
# ---------------------------------------------------------------------------

@dataclass
class SupportRequest:
    """
    Channel-agnostic representation of a customer request.

    Voice adapter converts: VoiceSession + STT transcript → SupportRequest
    Chat adapter converts: HTTP body → SupportRequest
    """
    message: str
    channel: str                     # "chat" | "voice"
    tenant_id: str
    customer_id: str
    session_id: Optional[str] = None
    case_id: Optional[str] = None
    language: str = "en"
    detected_language: Optional[str] = None

    # Auth state at the time of the request
    auth_level: str = "anonymous"
    verified: bool = False
    verified_customer: bool = False
    verified_order_ids: List[str] = field(default_factory=list)
    customer_contact: Optional[str] = None

    # Conversation memory flowing in
    memory: Dict[str, Any] = field(default_factory=dict)
    """
    Canonical memory keys:
    - active_intent: str           — last confirmed customer goal
    - active_case_type: str        — "damaged_return" | "order_status" | ...
    - pending_action: str          — next expected action if mid-flow
    - pending_order_id: str
    - pending_contact: str
    - last_tool_name: str
    - last_tool_result: dict
    - photos_requested: bool
    - photos_received: bool
    - conversation_turns: list     — [{role, text, intent}]
    - needs_identity: bool
    - issue_type: str
    """


# ---------------------------------------------------------------------------
# SupportIntent — structured decision contract from Supervisor
# ---------------------------------------------------------------------------

@dataclass
class SupportIntent:
    """
    The Supervisor's structured classification of a SupportRequest.

    intent_type is the primary routing key:
    - "knowledge"      → RAG → QA (no tool needed)
    - "transactional"  → direct tool (order status, tracking) → QA
    - "action"         → identity gate → planner → executor → verifier → QA
    - "conversational" → direct QA (greeting, smalltalk, affirmation, etc.)
    """
    intent: str                             # return | refund | cancel | track | order_status | policy_query | general
    intent_type: str                        # knowledge | transactional | action | conversational
    requires_rag: bool = False
    requires_identity: bool = False
    requires_tool: bool = False
    tool_name: Optional[str] = None         # shopify_get_order | stripe_refund | shopify_initiate_return
    response_mode: str = "conversational"   # direct | challenge | conversational
    confidence: float = 1.0
    risk: str = "low"
    needs_escalation: bool = False
    affirmation_of: Optional[str] = None    # intent being confirmed if this is "yes/ok/sure"

    # Derived from conversation context
    is_continuation: bool = False           # True when message continues previous turn's intent
    active_intent_carried: Optional[str] = None   # active_intent from previous turn


# ---------------------------------------------------------------------------
# SupportAction — a single tool invocation record
# ---------------------------------------------------------------------------

@dataclass
class SupportAction:
    """
    One tool invocation within a support workflow.
    Recorded in per-turn traces for observability.
    """
    tool_name: str
    tool_input: Dict[str, Any] = field(default_factory=dict)
    tool_result: Optional[Dict[str, Any]] = None
    success: bool = False
    latency_ms: float = 0.0
    verified: bool = False
    verification_notes: str = ""
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# SupportResponse — unified output contract for all channels
# ---------------------------------------------------------------------------

@dataclass
class SupportResponse:
    """
    Channel-agnostic support response.

    Chat: serialized to JSON HTTP response
    Voice: .response_text passed through Voice Response Shaper → TTS
    """
    response_text: str
    intent: Optional[str] = None
    intent_type: Optional[str] = None
    confidence: float = 0.0
    citations: List[str] = field(default_factory=list)
    escalated: bool = False
    blocked: bool = False
    needs_identity: bool = False
    identity_blocked: bool = False
    identity_challenge: Optional[Dict[str, Any]] = None
    auth_level: str = "anonymous"
    order_id: Optional[str] = None
    missing_inputs: List[str] = field(default_factory=list)
    tool_results: Dict[str, Any] = field(default_factory=dict)
    actions_taken: List[SupportAction] = field(default_factory=list)
    request_id: Optional[str] = None
    session_id: Optional[str] = None
    case_id: Optional[str] = None
    risk_level: Optional[str] = None
    status: str = "open"
    error: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    # Updated memory to write back to VoiceSession / Chat session
    updated_memory: Dict[str, Any] = field(default_factory=dict)
    """
    Keys the channel adapter should write back to session:
    - active_intent, active_case_type, pending_action
    - needs_identity, pending_order_id, pending_contact, auth_level
    - photos_requested, photos_received
    - last_tool_name, last_tool_result
    """
