import os
import time
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

from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

app = FastAPI(title="D2C AI Support Agent")


class ChatRequest(BaseModel):
    message: str
    customer_id: str = "default"
    tenant_id: str = "zepto"


@traceable(name="d2c_chat_request")
def run_graph(inputs: dict, tenant_id: str, customer_id: str):
    """Run the LangGraph with LangSmith metadata."""
    run = get_current_run_tree()
    if run:
        run.add_metadata({
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "request_id": inputs.get("request_id")
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

    # ---- Metrics: start ----
    ACTIVE_REQUESTS.inc()
    start_time = time.time()
    # ------------------------

    log_event("request_received", request_id, data={
        "tenant_id": request.tenant_id,
        "customer_id": request.customer_id,
        "message": request.message
    })

    try:
        tenant_config = load_tenant_config(request.tenant_id)
    except Exception as e:
        REQUEST_COUNT.labels(tenant_id=request.tenant_id, status="error").inc()
        ACTIVE_REQUESTS.dec()
        log_event("tenant_load_failed", request_id, data={"error": str(e)}, level="error")
        return {"error": f"Invalid tenant: {str(e)}"}

    inputs = {
        "messages": [HumanMessage(content=request.message)],
        "customer_id": request.customer_id,
        "tenant_id": request.tenant_id,
        "tenant_config": tenant_config.dict(),
        "request_id": request_id,
        "customer_context": {},
        "current_plan": None,
        "workflow_steps": [],
        "tool_results": {},
        "confidence": 0.0,
        "citations": [],
        "memory_retrieved": [],
        "risk_level": "low",
        "needs_escalation": False,
        "escalation_reason": "",
        "verification_passed": True,
        "verification_issues": [],
        "missing_photos": False
    }

    try:
        result = run_graph(
            inputs,
            tenant_id=request.tenant_id,
            customer_id=request.customer_id
        )

        latency = time.time() - start_time
        REQUEST_LATENCY.labels(tenant_id=request.tenant_id).observe(latency)

        # ---- Record outcome metrics ----
        if result.get("blocked"):
            BLOCK_COUNT.labels(tenant_id=request.tenant_id).inc()
            REQUEST_COUNT.labels(tenant_id=request.tenant_id, status="blocked").inc()
        elif result.get("needs_escalation"):
            ESCALATION_COUNT.labels(
                tenant_id=request.tenant_id,
                reason=(result.get("escalation_reason") or "unknown")[:50]
            ).inc()
            REQUEST_COUNT.labels(tenant_id=request.tenant_id, status="escalated").inc()
        else:
            REQUEST_COUNT.labels(tenant_id=request.tenant_id, status="success").inc()
        # --------------------------------

        log_event("request_completed", request_id, data={
            "latency": round(latency, 3),
            "escalated": result.get("needs_escalation", False),
            "blocked": result.get("blocked", False),
            "confidence": result.get("confidence"),
            "intent": (result.get("current_plan") or {}).get("intent")
        })

        # 1. Guardrails blocked
        if result.get("blocked") is True:
            return {
                "response": result.get("error", "I can only assist with Zepto-related customer support queries."),
                "escalated": False,
                "blocked": True,
                "confidence": 0.0,
                "citations": [],
                "request_id": request_id
            }

        # 2. Verification failed
        if result.get("verification_passed") is False:
            return {
                "response": "I was unable to fully process your request due to an internal issue. A support agent will review this case shortly.",
                "escalated": True,
                "reason": result.get("escalation_reason", "Verification failed"),
                "confidence": 0.0,
                "citations": [],
                "request_id": request_id
            }

        # 3. HITL escalation
        if result.get("needs_escalation") is True:
            return {
                "response": "This request requires human assistance. A support agent will review your case shortly.",
                "escalated": True,
                "reason": result.get("escalation_reason", "Requires manual review"),
                "confidence": result.get("confidence", 0.0),
                "citations": result.get("citations", []),
                "request_id": request_id
            }

        # 4. Normal response
        messages = result.get("messages", [])
        if not messages:
            return {
                "response": "I could not generate a response. Please try again.",
                "escalated": False,
                "confidence": 0.0,
                "citations": [],
                "request_id": request_id
            }

        last_msg = messages[-1]
        response_text = get_message_content(last_msg)

        if response_text.strip() == request.message.strip():
            return {
                "response": "I can only assist with Zepto-related customer support queries such as orders, returns, refunds, delivery, and payments.",
                "escalated": False,
                "blocked": True,
                "confidence": 0.0,
                "citations": [],
                "request_id": request_id
            }

        return {
            "response": response_text,
            "confidence": result.get("confidence", 0.0),
            "citations": result.get("citations", []),
            "escalated": False,
            "tool_results": result.get("tool_results", {}),
            "request_id": request_id
        }

    except Exception as e:
        REQUEST_COUNT.labels(tenant_id=request.tenant_id, status="error").inc()
        log_event("request_failed", request_id, data={"error": str(e)}, level="error")
        return {
            "error": str(e),
            "escalated": False,
            "request_id": request_id
        }
    finally:
        ACTIVE_REQUESTS.dec()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)