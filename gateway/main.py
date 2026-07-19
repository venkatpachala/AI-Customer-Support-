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
        "verification_issues": []
    }

    try:
        result = compiled_graph.invoke(inputs)

        # 1. Verification failed
        if result.get("verification_passed") is False:
            issues = result.get("verification_issues", [])
            return {
                "response": "I was unable to fully process your request due to an internal issue. A support agent will review this case shortly.",
                "escalated": True,
                "reason": result.get("escalation_reason", "Verification failed"),
                "verification_issues": issues,
                "confidence": 0.0,
                "citations": []
            }

        # 2. Normal HITL escalation
        if result.get("needs_escalation"):
            return {
                "response": "This request requires human assistance. A support agent will review your case shortly.",
                "escalated": True,
                "reason": result.get("escalation_reason", "Requires manual review"),
                "confidence": result.get("confidence", 0.0),
                "citations": result.get("citations", [])
            }

        # 3. Normal successful response
        last_msg = result["messages"][-1]
        response_text = get_message_content(last_msg)

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