import os
import time
from typing import Optional
from dotenv import load_dotenv

load_dotenv(override=True)

# Enable LangSmith tracing
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGCHAIN_PROJECT", "d2c-support-agent")

print("DEBUG: OPENAI_API_KEY loaded =", "YES" if os.getenv("OPENAI_API_KEY") else "NO")
print("DEBUG: PINECONE_API_KEY loaded =", "YES" if os.getenv("PINECONE_API_KEY") else "NO")
print("DEBUG: LANGSMITH tracing =", os.getenv("LANGCHAIN_TRACING_V2"))

from fastapi import FastAPI
from pydantic import BaseModel
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

from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

app = FastAPI(title="D2C AI Support Agent")
memory_service = MemoryService()


class ChatRequest(BaseModel):
    message: str
    customer_id: str = "default"
    tenant_id: str = "zepto"
    session_id: Optional[str] = None


@traceable(name="d2c_chat_request")
def run_graph(inputs: dict, tenant_id: str, customer_id: str):
    run = get_current_run_tree()
    if run:
        run.add_metadata({
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "request_id": inputs.get("request_id"),
            "session_id": inputs.get("session_id"),
            "case_id": inputs.get("case_id")
        })
        run.add_tags([
            f"tenant:{tenant_id}",
            f"customer:{customer_id}"
        ])
    return compiled_graph.invoke(inputs)


@app.get("/metrics")
def metrics():
    return metrics_endpoint()


@app.post("/chat")
async def chat(request: ChatRequest):
    request_id = new_request_id()
    ACTIVE_REQUESTS.inc()
    start_time = time.time()

    log_event("request_received", request_id, data={
        "tenant_id": request.tenant_id,
        "customer_id": request.customer_id,
        "session_id": request.session_id,
        "message": request.message
    })

    # -------- Load tenant config --------
    try:
        tenant_config = load_tenant_config(request.tenant_id)
    except Exception as e:
        REQUEST_COUNT.labels(tenant_id=request.tenant_id, status="error").inc()
        ACTIVE_REQUESTS.dec()
        return {"error": f"Invalid tenant: {str(e)}"}

    # -------- Load / create memory --------
    session = memory_service.get_or_create_session(
        customer_id=request.customer_id,
        tenant_id=request.tenant_id,
        session_id=request.session_id
    )
    case = memory_service.get_or_create_active_case(session)

    # Append user message
    memory_service.append_message(session, role="user", content=request.message)
    memory_context = memory_service.to_state_context(session, case)

    inputs = {
        "messages": [HumanMessage(content=request.message)],
        "customer_id": request.customer_id,
        "tenant_id": request.tenant_id,
        "tenant_config": tenant_config.dict(),
        "request_id": request_id,
        "session_id": session.session_id,
        "case_id": case.case_id,
        "customer_context": {},
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
        "missing_photos": "photos" in (case.missing_inputs or [])
    }

    try:
        result = run_graph(
            inputs,
            tenant_id=request.tenant_id,
            customer_id=request.customer_id
        )

        latency = time.time() - start_time
        REQUEST_LATENCY.labels(tenant_id=request.tenant_id).observe(latency)

        blocked = result.get("blocked", False)
        escalated = result.get("needs_escalation", False)

        # Metrics
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

        # -------- Prepare response text --------
        if blocked:
            response_text = result.get(
                "error",
                "I can only assist with Zepto-related customer support queries."
            )
        elif result.get("verification_passed") is False:
            response_text = "I was unable to fully process your request due to an internal issue. A support agent will review this case shortly."
            escalated = True
        elif escalated:
            response_text = "This request requires human assistance. A support agent will review your case shortly."
        else:
            messages = result.get("messages", [])
            if not messages:
                response_text = "I could not generate a response. Please try again."
            else:
                response_text = get_message_content(messages[-1])
                if response_text.strip() == request.message.strip():
                    response_text = "I can only assist with Zepto-related customer support queries such as orders, returns, refunds, delivery, and payments."
                    blocked = True

        # -------- Write memory back --------
        plan = result.get("current_plan") or {}
        tool_results = result.get("tool_results") or {}
        citations = result.get("citations") or []

        missing_inputs = plan.get("missing_inputs") or case.missing_inputs or []
        photos_requested = case.photos_requested or ("photos" in missing_inputs)
        issue_type = plan.get("intent") or case.issue_type

        # try to persist order id from memory/plan/tools if present
        order_id = case.order_id
        if not order_id:
            order_id = memory_context.get("active_order_id")

        status = case.status
        if blocked:
            status = case.status
        elif escalated:
            status = "escalated"
        elif "photos" in missing_inputs:
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
            tools_executed=list(tool_results.keys()),
            tool_results_summary=tool_results,
            policy_citations=citations,
            escalated=escalated,
            escalation_reason=result.get("escalation_reason"),
            last_agent_action="responded",
            status=status
        )

        log_event("request_completed", request_id, data={
            "latency": round(latency, 3),
            "escalated": escalated,
            "blocked": blocked,
            "session_id": session.session_id,
            "case_id": case.case_id,
            "confidence": result.get("confidence"),
            "intent": issue_type
        })

        return {
            "response": response_text,
            "confidence": result.get("confidence", 0.0),
            "citations": citations,
            "escalated": escalated,
            "blocked": blocked,
            "reason": result.get("escalation_reason"),
            "tool_results": tool_results,
            "request_id": request_id,
            "session_id": session.session_id,
            "case_id": case.case_id,
            "missing_inputs": missing_inputs
        }

    except Exception as e:
        REQUEST_COUNT.labels(tenant_id=request.tenant_id, status="error").inc()
        log_event("request_failed", request_id, data={"error": str(e)}, level="error")
        return {
            "error": str(e),
            "escalated": False,
            "request_id": request_id,
            "session_id": session.session_id if session else None
        }
    finally:
        ACTIVE_REQUESTS.dec()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)