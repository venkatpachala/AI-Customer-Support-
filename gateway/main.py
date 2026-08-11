import os
import re
import time
import json
from typing import Optional, List
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv(override=True)

# Enable LangSmith tracing
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGCHAIN_PROJECT", "d2c-support-agent")

print("DEBUG: OPENAI_API_KEY loaded =", "YES" if os.getenv("OPENAI_API_KEY") else "NO")
print("DEBUG: PINECONE_API_KEY loaded =", "YES" if os.getenv("PINECONE_API_KEY") else "NO")
print("DEBUG: LANGSMITH tracing =", os.getenv("LANGCHAIN_TRACING_V2"))
print("DEBUG: TOOLS_MODE =", os.getenv("TOOLS_MODE", "mock"))

from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from tools.bootstrap import register_default_tools
register_default_tools()

from pydantic import BaseModel, Field
from orchestration.graph import compiled_graph
from langchain_core.messages import HumanMessage
from common.messages import get_message_content
from config.loaders import load_tenant_config
from observability.logging import new_request_id, log_event
from observability.metrics import (
    REQUEST_COUNT,
    ESCALATION_COUNT,
    BLOCK_COUNT,
    REQUEST_LATENCY,
    ACTIVE_REQUESTS,
    metrics_endpoint
)
from memory.service import MemoryService
from interactions.service import InteractionService
from security.output_guard import apply_output_guard
from rag.policy_cache import policy_cache
from db.session import init_db

from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="D2C AI Support Agent", lifespan=lifespan)
memory_service = MemoryService()
interaction_service = InteractionService()


class ChatRequest(BaseModel):
    message: str
    customer_id: str = "default"
    tenant_id: str = "zepto"
    session_id: Optional[str] = None

    # Trusted identity context from backend/app (preferred)
    auth_level: str = "anonymous"  # anonymous | identified | verified
    verified: bool = False
    verified_order_ids: List[str] = Field(default_factory=list)

    # Backward-compatible aliases
    verified_customer: bool = False
    contact: Optional[str] = None  # ignored for identity; kept for compatibility


def normalize_auth_level(auth_level: str, verified: bool = False, verified_customer: bool = False) -> str:
    level = (auth_level or "anonymous").lower().strip()
    if verified or verified_customer or level == "verified":
        return "verified"
    if level in {"anonymous", "identified", "verified"}:
        return level
    return "anonymous"


def extract_order_id(text: str) -> Optional[str]:
    if not text:
        return None
    match = re.search(r'(?:order\s*#?|#)\s*(\d{5,})', text, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r'\border\b.*?(\d{5,})', text, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def detect_photos_received(message: str) -> bool:
    msg = (message or "").lower()
    triggers = [
        "uploaded the photo",
        "uploaded photos",
        "uploaded the photos",
        "shared the photo",
        "shared photos",
        "shared the photos",
        "attached photo",
        "attached photos",
        "here are the photos",
        "photo uploaded",
        "photos uploaded",
    ]
    return any(t in msg for t in triggers)


def requires_verified_customer(message: str, tenant_config: dict) -> bool:
    msg = (message or "").lower()

    amount = 0
    m = re.search(
        r'(?:refund|amount|pay|paid|worth|value)\s*(?:of|is|for)?\s*(?:₹|rs\.?|inr)?\s*(\d{3,6})',
        msg,
    )
    if not m:
        m = re.search(r'(?:₹|rs\.?|inr)\s*(\d{3,6})', msg)
    if m:
        amount = int(m.group(1))

    approval = (tenant_config or {}).get("approval", {})
    high_value_limit = float(approval.get("high_value_refund_limit", 2000))
    return amount >= high_value_limit


def looks_like_policy_query(message: str) -> bool:
    text = (message or "").lower()
    policy_signals = [
        "policy",
        "return policy",
        "refund policy",
        "cancellation policy",
        "what is the",
        "how long does",
        "how many days",
        "do you accept returns",
        "terms of use",
    ]
    hard_action_signals = [
        "order #",
        "order id",
        "my order",
        "refund of",
        "i want a refund",
        "cancel my order",
        "arrived damaged",
        "is damaged",
        "received damaged",
    ]
    if any(k in text for k in hard_action_signals):
        return False
    return any(k in text for k in policy_signals)


@traceable(name="d2c_chat_request")
def run_graph(inputs: dict, tenant_id: str, customer_id: str):
    run = get_current_run_tree()
    if run:
        run.add_metadata({
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "request_id": inputs.get("request_id"),
            "session_id": inputs.get("session_id"),
            "case_id": inputs.get("case_id"),
            "auth_level": inputs.get("auth_level"),
            "verified": inputs.get("verified"),
        })
        run.add_tags([
            f"tenant:{tenant_id}",
            f"customer:{customer_id}",
            f"auth:{inputs.get('auth_level', 'anonymous')}",
        ])
    return compiled_graph.invoke(inputs)


@app.get("/metrics")
def metrics():
    return metrics_endpoint()


@app.get("/interactions/recent")
def get_recent_interactions(
    limit: int = Query(20, ge=1, le=200),
    tenant_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    escalated: Optional[bool] = None,
):
    records = interaction_service.get_recent(
        limit=limit,
        tenant_id=tenant_id,
        customer_id=customer_id,
        escalated=escalated,
    )
    return {
        "count": len(records),
        "items": [r.dict() for r in records],
    }


@app.get("/interactions/conversation/{conversation_id}")
def get_conversation_interactions(conversation_id: str):
    records = interaction_service.store.list_by_conversation(conversation_id)
    return {
        "conversation_id": conversation_id,
        "count": len(records),
        "items": [r.dict() for r in records],
    }


@app.post("/chat")
async def chat(request: ChatRequest):
    request_id = new_request_id()
    ACTIVE_REQUESTS.inc()
    start_time = time.time()

    auth_level = normalize_auth_level(
        request.auth_level,
        verified=request.verified,
        verified_customer=request.verified_customer,
    )
    is_verified = auth_level == "verified"
    verified_order_ids = list(request.verified_order_ids or [])

    log_event("request_received", request_id, data={
        "tenant_id": request.tenant_id,
        "customer_id": request.customer_id,
        "session_id": request.session_id,
        "message": request.message,
        "auth_level": auth_level,
        "verified": is_verified,
        "verified_order_ids": verified_order_ids,
    })

    # -------- Load tenant config --------
    try:
        tenant_config = load_tenant_config(request.tenant_id)
        tenant_config_dict = tenant_config.dict() if hasattr(tenant_config, "dict") else tenant_config
    except Exception as e:
        REQUEST_COUNT.labels(tenant_id=request.tenant_id, status="error").inc()
        ACTIVE_REQUESTS.dec()
        return {"error": f"Invalid tenant: {str(e)}"}

    # -------- Policy cache short-circuit --------
    if looks_like_policy_query(request.message):
        cached = policy_cache.get(request.tenant_id, request.message)
        if cached:
            try:
                REQUEST_COUNT.labels(tenant_id=request.tenant_id, status="success").inc()
                REQUEST_LATENCY.labels(tenant_id=request.tenant_id).observe(time.time() - start_time)
            except Exception:
                pass
            ACTIVE_REQUESTS.dec()
            cached = dict(cached)
            cached["request_id"] = request_id
            cached["cached"] = True
            cached["auth_level"] = auth_level
            return cached

    # -------- Load / create memory --------
    session = memory_service.get_or_create_session(
        customer_id=request.customer_id,
        tenant_id=request.tenant_id,
        session_id=request.session_id
    )
    case = memory_service.get_or_create_active_case(session)

    # -------- Sticky escalation short-circuit (FIRST) --------
    if case.status == "escalated":
        memory_service.append_message(session, role="user", content=request.message)
        response_text = (
            "This case has already been escalated to a human support agent. "
            "They will review it and get back to you shortly."
        )
        memory_service.append_message(session, role="assistant", content=response_text)

        latency = time.time() - start_time
        try:
            REQUEST_LATENCY.labels(tenant_id=request.tenant_id).observe(latency)
            ESCALATION_COUNT.labels(
                tenant_id=request.tenant_id,
                reason=(case.escalation_reason or "already_escalated")[:50]
            ).inc()
            REQUEST_COUNT.labels(tenant_id=request.tenant_id, status="escalated").inc()
        except Exception:
            pass

        resolved_order_id = case.order_id or extract_order_id(request.message)

        try:
            interaction_service.log_chat_turn(
                conversation_id=session.session_id,
                case_id=case.case_id,
                tenant_id=request.tenant_id,
                customer_id=request.customer_id,
                message=request.message,
                response=response_text,
                intent=case.issue_type,
                risk_level="high",
                order_id=resolved_order_id,
                missing_inputs=case.missing_inputs or [],
                photos_requested=bool(case.photos_requested),
                photos_received=bool(case.photos_received),
                tool_results={},
                escalated=True,
                blocked=False,
                escalation_reason=case.escalation_reason,
                citations=case.policy_citations or [],
                confidence=1.0,
                latency_ms=round(latency * 1000.0, 2),
                status="escalated",
                request_id=request_id,
                metadata={
                    "short_circuit": "already_escalated",
                    "auth_level": auth_level,
                },
            )
        except Exception as e:
            log_event("interaction_log_failed", request_id, data={"error": str(e)}, level="warning")

        ACTIVE_REQUESTS.dec()
        return {
            "response": response_text,
            "confidence": 1.0,
            "citations": case.policy_citations or [],
            "escalated": True,
            "blocked": False,
            "reason": case.escalation_reason or "Case already escalated",
            "tool_results": {},
            "request_id": request_id,
            "session_id": session.session_id,
            "case_id": case.case_id,
            "missing_inputs": case.missing_inputs or [],
            "auth_level": auth_level,
            "identity_blocked": False,
        }

    # -------- Gateway high-value short-circuit if not verified --------
    if requires_verified_customer(request.message, tenant_config_dict) and not is_verified:
        response_text = (
            "For security, high-value refund or account-sensitive requests require account verification. "
            "Please continue from your logged-in/verified account or contact support."
        )

        memory_service.append_message(session, role="user", content=request.message)
        memory_service.append_message(session, role="assistant", content=response_text)

        latency = time.time() - start_time
        try:
            REQUEST_LATENCY.labels(tenant_id=request.tenant_id).observe(latency)
            ESCALATION_COUNT.labels(
                tenant_id=request.tenant_id,
                reason="unverified_sensitive_action"[:50]
            ).inc()
            REQUEST_COUNT.labels(tenant_id=request.tenant_id, status="escalated").inc()
        except Exception:
            pass

        order_id = case.order_id or extract_order_id(request.message)

        try:
            memory_service.update_case_from_result(
                case,
                order_id=order_id,
                issue_type="refund",
                escalated=True,
                escalation_reason="Unverified customer attempted sensitive/high-value action",
                status="escalated",
                last_agent_action="verification_required",
            )
        except Exception:
            pass

        try:
            interaction_service.log_chat_turn(
                conversation_id=session.session_id,
                case_id=case.case_id,
                tenant_id=request.tenant_id,
                customer_id=request.customer_id,
                message=request.message,
                response=response_text,
                intent="refund",
                risk_level="high",
                order_id=order_id,
                missing_inputs=case.missing_inputs or [],
                photos_requested=bool(getattr(case, "photos_requested", False)),
                photos_received=bool(getattr(case, "photos_received", False)),
                tool_results={},
                escalated=True,
                blocked=False,
                escalation_reason="Unverified customer attempted sensitive/high-value action",
                citations=[],
                confidence=1.0,
                latency_ms=round(latency * 1000.0, 2),
                status="escalated",
                request_id=request_id,
                metadata={
                    "reason": "unverified_sensitive_action",
                    "auth_level": auth_level,
                },
            )
        except Exception as e:
            log_event("interaction_log_failed", request_id, data={"error": str(e)}, level="warning")

        ACTIVE_REQUESTS.dec()
        return {
            "response": response_text,
            "confidence": 1.0,
            "citations": [],
            "escalated": True,
            "blocked": False,
            "reason": "Unverified customer attempted sensitive/high-value action",
            "tool_results": {},
            "request_id": request_id,
            "session_id": session.session_id,
            "case_id": case.case_id,
            "missing_inputs": case.missing_inputs or [],
            "auth_level": auth_level,
            "identity_blocked": True,
        }

    # Append user message
    memory_service.append_message(session, role="user", content=request.message)

    # Photo received detection on follow-up
    photos_received = case.photos_received
    missing_inputs: List[str] = list(case.missing_inputs or [])
    if detect_photos_received(request.message):
        photos_received = True
        missing_inputs = [m for m in missing_inputs if m != "photos"]
        case = memory_service.update_case_from_result(
            case,
            photos_received=True,
            missing_inputs=missing_inputs,
            status="open" if case.status == "waiting_customer" else case.status,
        )

    memory_context = memory_service.to_state_context(session, case) or {}
    memory_context["auth_level"] = auth_level
    memory_context["verified_order_ids"] = verified_order_ids

    inputs = {
        "messages": [HumanMessage(content=request.message)],
        "customer_id": request.customer_id,
        "tenant_id": request.tenant_id,
        "tenant_config": tenant_config_dict,
        "request_id": request_id,
        "session_id": session.session_id,
        "case_id": case.case_id,

        # Trusted identity context for identity_gate_node
        "auth_level": auth_level,
        "verified": is_verified,
        "verified_order_ids": verified_order_ids,
        "customer_context": {
            "verified_customer": is_verified,
            "auth_level": auth_level,
            "verified_order_ids": verified_order_ids,
        },

        "memory_context": memory_context,
        "current_plan": None,
        "workflow_steps": [],
        "tool_results": {},
        "confidence": 0.0,
        "citations": [],
        "memory_retrieved": memory_context.get("recent_messages", []),
        "risk_level": "low",
        "needs_escalation": False,
        "escalation_reason": "",
        "verification_passed": True,
        "verification_issues": [],
        "missing_photos": ("photos" in (case.missing_inputs or [])) and not case.photos_received,
    }

    try:
        result = run_graph(
            inputs,
            tenant_id=request.tenant_id,
            customer_id=request.customer_id
        )

        latency = time.time() - start_time
        try:
            REQUEST_LATENCY.labels(tenant_id=request.tenant_id).observe(latency)
        except Exception:
            pass

        blocked = bool(result.get("blocked", False))
        escalated = bool(result.get("needs_escalation", False))
        identity_blocked = bool(result.get("identity_blocked", False))
        identity_challenge = result.get("identity_challenge") or {}
        result_auth_level = result.get("auth_level") or auth_level

        # -------- Identity challenge short-circuit --------
        if identity_blocked and identity_challenge.get("message"):
            response_text = identity_challenge["message"]
            escalated = escalated or bool(result.get("needs_escalation", False))

            try:
                if escalated:
                    ESCALATION_COUNT.labels(
                        tenant_id=request.tenant_id,
                        reason=(result.get("escalation_reason") or "identity_blocked")[:50]
                    ).inc()
                    REQUEST_COUNT.labels(tenant_id=request.tenant_id, status="escalated").inc()
                else:
                    REQUEST_COUNT.labels(tenant_id=request.tenant_id, status="success").inc()
                REQUEST_LATENCY.labels(tenant_id=request.tenant_id).observe(latency)
            except Exception:
                pass

            memory_service.append_message(session, role="assistant", content=response_text)

            order_id = (
                result.get("resolved_order_id")
                or case.order_id
                or extract_order_id(request.message)
            )

            status = "escalated" if escalated else "waiting_customer"
            try:
                memory_service.update_case_from_result(
                    case,
                    order_id=order_id,
                    issue_type=result.get("intent") or case.issue_type,
                    missing_inputs=result.get("missing_inputs") or case.missing_inputs or [],
                    escalated=escalated,
                    escalation_reason=result.get("escalation_reason") if escalated else case.escalation_reason,
                    last_agent_action="identity_challenge",
                    status=status,
                )
            except Exception:
                pass

            payload = {
                "response": response_text,
                "confidence": 1.0,
                "citations": [],
                "escalated": escalated,
                "blocked": False,
                "reason": result.get("escalation_reason") if escalated else identity_challenge.get("type"),
                "tool_results": result.get("tool_results") or {},
                "request_id": request_id,
                "session_id": session.session_id,
                "case_id": case.case_id,
                "missing_inputs": result.get("missing_inputs") or [],
                "auth_level": result_auth_level,
                "identity_blocked": True,
            }

            try:
                interaction_service.log_chat_turn(
                    conversation_id=session.session_id,
                    case_id=case.case_id,
                    tenant_id=request.tenant_id,
                    customer_id=request.customer_id,
                    message=request.message,
                    response=response_text,
                    intent=result.get("intent") or case.issue_type,
                    risk_level=result.get("risk_level") or "low",
                    order_id=order_id,
                    missing_inputs=result.get("missing_inputs") or [],
                    photos_requested=bool(getattr(case, "photos_requested", False)),
                    photos_received=bool(getattr(case, "photos_received", False)),
                    tool_results=result.get("tool_results") or {},
                    escalated=escalated,
                    blocked=False,
                    escalation_reason=result.get("escalation_reason") if escalated else None,
                    citations=[],
                    confidence=1.0,
                    latency_ms=round(latency * 1000.0, 2),
                    status=status,
                    request_id=request_id,
                    metadata={
                        "identity_blocked": True,
                        "identity_challenge": identity_challenge,
                        "auth_level": result_auth_level,
                    },
                )
            except Exception as e:
                log_event("interaction_log_failed", request_id, data={"error": str(e)}, level="warning")

            return payload

        try:
            if blocked:
                BLOCK_COUNT.labels(tenant_id=request.tenant_id).inc()
                REQUEST_COUNT.labels(tenant_id=request.tenant_id, status="blocked").inc()
            elif escalated:
                ESCALATION_COUNT.labels(
                    tenant_id=request.tenant_id,
                    reason=(result.get("escalation_reason") or "unknown")[:50]
                ).inc()
                REQUEST_COUNT.labels(tenant_id=request.tenant_id, status="escalated").inc()
            else:
                REQUEST_COUNT.labels(tenant_id=request.tenant_id, status="success").inc()
        except Exception:
            pass

        # -------- Prepare response text --------
        if blocked:
            response_text = result.get(
                "error",
                "I can only assist with Zepto-related customer support queries."
            )
        elif result.get("verification_passed") is False:
            response_text = (
                "I was unable to fully process your request due to an internal issue. "
                "A support agent will review this case shortly."
            )
            escalated = True
        elif escalated:
            response_text = (
                "This request requires human assistance. "
                "A support agent will review your case shortly."
            )
        else:
            messages = result.get("messages", [])
            if not messages:
                response_text = "I could not generate a response. Please try again."
            else:
                response_text = get_message_content(messages[-1])
                if response_text.strip() == request.message.strip():
                    response_text = (
                        "I can only assist with Zepto-related customer support queries "
                        "such as orders, returns, refunds, delivery, and payments."
                    )
                    blocked = True

        # -------- Output hallucination guard --------
        guard = apply_output_guard(
            response_text,
            tool_results=result.get("tool_results") or {},
            escalated=escalated,
            blocked=blocked,
        )
        if guard.get("flagged"):
            response_text = guard["text"]
            log_event(
                "output_guard_flagged",
                request_id,
                data={"reasons": guard.get("reasons", [])},
                level="warning",
            )

        # -------- Write memory back --------
        plan = result.get("current_plan") or {}
        tool_results = result.get("tool_results") or {}
        citations = result.get("citations") or []

        plan_missing = list(plan.get("missing_inputs") or [])
        missing_inputs = plan_missing or list(case.missing_inputs or [])

        if result.get("missing_photos") and "photos" not in missing_inputs and not photos_received:
            missing_inputs.append("photos")

        if photos_received:
            missing_inputs = [m for m in missing_inputs if m != "photos"]

        photos_requested = bool(
            case.photos_requested
            or ("photos" in missing_inputs)
            or result.get("missing_photos", False)
        )

        issue_type = plan.get("intent") or result.get("intent") or case.issue_type

        order_id = (
            result.get("resolved_order_id")
            or case.order_id
            or memory_context.get("active_order_id")
            or extract_order_id(request.message)
        )

        if blocked:
            status = "blocked"
        elif escalated:
            status = "escalated"
        elif "photos" in missing_inputs and not photos_received:
            status = "waiting_customer"
        else:
            status = "open"

        memory_service.append_message(session, role="assistant", content=response_text)

        memory_service.update_case_from_result(
            case,
            order_id=order_id,
            issue_type=issue_type,
            missing_inputs=missing_inputs,
            photos_requested=photos_requested,
            photos_received=photos_received,
            tools_executed=list(tool_results.keys()),
            tool_results_summary=tool_results,
            policy_citations=citations,
            escalated=escalated,
            escalation_reason=result.get("escalation_reason") if escalated else case.escalation_reason,
            last_agent_action="responded",
            status=status if status != "blocked" else case.status
        )

        response_payload = {
            "response": response_text,
            "confidence": result.get("confidence", 0.0),
            "citations": citations,
            "escalated": escalated,
            "blocked": blocked,
            "reason": result.get("escalation_reason") if escalated else None,
            "tool_results": tool_results,
            "request_id": request_id,
            "session_id": session.session_id,
            "case_id": case.case_id,
            "missing_inputs": missing_inputs,
            "auth_level": result_auth_level,
            "identity_blocked": identity_blocked,
        }

        # -------- Cache policy answers --------
        if (
            not escalated
            and not blocked
            and looks_like_policy_query(request.message)
        ):
            policy_cache.set(request.tenant_id, request.message, response_payload)

        # -------- Persist interaction intelligence --------
        try:
            interaction_service.log_chat_turn(
                conversation_id=session.session_id,
                case_id=case.case_id,
                tenant_id=request.tenant_id,
                customer_id=request.customer_id,
                message=request.message,
                response=response_text,
                intent=issue_type,
                risk_level=result.get("risk_level"),
                order_id=order_id,
                missing_inputs=missing_inputs,
                photos_requested=photos_requested,
                photos_received=photos_received,
                tool_results=tool_results,
                escalated=escalated,
                blocked=blocked,
                escalation_reason=result.get("escalation_reason") if escalated else None,
                citations=citations,
                confidence=float(result.get("confidence") or 0.0),
                latency_ms=round(latency * 1000.0, 2),
                status=status,
                request_id=request_id,
                metadata={
                    "tools_mode": os.getenv("TOOLS_MODE", "mock"),
                    "verification_passed": result.get("verification_passed", True),
                    "auth_level": result_auth_level,
                    "verified": is_verified,
                    "identity_blocked": identity_blocked,
                },
            )
        except Exception as e:
            log_event("interaction_log_failed", request_id, data={"error": str(e)}, level="warning")

        log_event("request_completed", request_id, data={
            "latency": round(latency, 3),
            "escalated": escalated,
            "blocked": blocked,
            "session_id": session.session_id,
            "case_id": case.case_id,
            "confidence": result.get("confidence"),
            "intent": issue_type,
            "missing_inputs": missing_inputs,
            "status": status,
            "order_id": order_id,
            "auth_level": result_auth_level,
            "identity_blocked": identity_blocked,
        })

        return response_payload

    except Exception as e:
        try:
            REQUEST_COUNT.labels(tenant_id=request.tenant_id, status="error").inc()
        except Exception:
            pass
        log_event("request_failed", request_id, data={"error": str(e)}, level="error")
        return {
            "error": str(e),
            "escalated": False,
            "request_id": request_id,
            "session_id": session.session_id if session else None
        }
    finally:
        ACTIVE_REQUESTS.dec()


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """
    Streams final response text.
    Uses cache when available; otherwise runs full /chat then streams the result.
    """
    if looks_like_policy_query(request.message):
        cached = policy_cache.get(request.tenant_id, request.message)
        if cached and cached.get("response"):
            text = cached["response"]

            async def cached_gen():
                for word in text.split(" "):
                    yield word + " "
                yield "\n"

            return StreamingResponse(cached_gen(), media_type="text/plain")

    result = await chat(request)
    if isinstance(result, dict) and result.get("response"):
        text = result["response"]

        async def gen():
            for word in text.split(" "):
                yield word + " "
            yield "\n"

        return StreamingResponse(gen(), media_type="text/plain")

    async def err_gen():
        yield json.dumps(result)

    return StreamingResponse(err_gen(), media_type="application/json")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)