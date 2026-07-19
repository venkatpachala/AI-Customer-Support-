import os
from dotenv import load_dotenv
load_dotenv(override=True)

print("DEBUG: OPENAI_API_KEY loaded =", "YES" if os.getenv("OPENAI_API_KEY") else "NO")
print("DEBUG: PINECONE_API_KEY loaded =", "YES" if os.getenv("PINECONE_API_KEY") else "NO")

from fastapi import FastAPI
from pydantic import BaseModel
from orchestration.graph import compiled_graph
from langchain_core.messages import HumanMessage
from common.messages import get_message_content
from config.loaders import load_tenant_config

app = FastAPI(title="D2C AI Support Agent")

class ChatRequest(BaseModel):
    message: str
    customer_id: str = "default"
    tenant_id: str = "zepto"

@app.post("/chat")
async def chat(request: ChatRequest):
    try:
        tenant_config = load_tenant_config(request.tenant_id)
    except Exception as e:
        return {"error": f"Invalid tenant: {str(e)}"}

    inputs = {
        "messages": [HumanMessage(content=request.message)],
        "customer_id": request.customer_id,
        "tenant_id": request.tenant_id,
        "tenant_config": tenant_config.dict(),
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
        result = compiled_graph.invoke(inputs)

        # ============================================
        # 1. FIRST: Check if Guardrails blocked it
        # ============================================
        if result.get("blocked") is True:
            return {
                "response": result.get("error", "I can only assist with Zepto-related customer support queries such as orders, returns, refunds, delivery, and payments."),
                "escalated": False,
                "blocked": True,
                "confidence": 0.0,
                "citations": []
            }

        # ============================================
        # 2. Verification failed
        # ============================================
        if result.get("verification_passed") is False:
            return {
                "response": "I was unable to fully process your request due to an internal issue. A support agent will review this case shortly.",
                "escalated": True,
                "reason": result.get("escalation_reason", "Verification failed"),
                "confidence": 0.0,
                "citations": []
            }

        # ============================================
        # 3. HITL escalation
        # ============================================
        if result.get("needs_escalation") is True:
            return {
                "response": "This request requires human assistance. A support agent will review your case shortly.",
                "escalated": True,
                "reason": result.get("escalation_reason", "Requires manual review"),
                "confidence": result.get("confidence", 0.0),
                "citations": result.get("citations", [])
            }

        # ============================================
        # 4. Normal response
        # ============================================
        messages = result.get("messages", [])
        if not messages:
            return {
                "response": "I could not generate a response. Please try again.",
                "escalated": False,
                "confidence": 0.0,
                "citations": []
            }

        last_msg = messages[-1]
        response_text = get_message_content(last_msg)

        # Safety: don't return the original user message
        if response_text.strip() == request.message.strip():
            return {
                "response": "I can only assist with Zepto-related customer support queries such as orders, returns, refunds, delivery, and payments.",
                "escalated": False,
                "blocked": True,
                "confidence": 0.0,
                "citations": []
            }

        return {
            "response": response_text,
            "confidence": result.get("confidence", 0.0),
            "citations": result.get("citations", []),
            "escalated": False,
            "tool_results": result.get("tool_results", {})
        }

    except Exception as e:
        print("Error during graph execution:", str(e))
        return {
            "error": str(e),
            "escalated": False
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)