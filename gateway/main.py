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

class ChatRequest(BaseModel):
    message: str
    customer_id: str = "default"

app = FastAPI(title="D2C AI Support Agent")

@app.post("/chat")
async def chat(request: ChatRequest):
    inputs = {
        "messages": [HumanMessage(content=request.message)],
        "customer_id": request.customer_id,
        "customer_context": {},
        "current_plan": None,
        "workflow_steps": [],
        "tool_results": {},
        "confidence": 0.0,
        "citations": [],
        "memory_retrieved": [],
        "risk_level": "low",
        "needs_escalation": False,
        "escalation_reason": ""
    }

    try:
        result = compiled_graph.invoke(inputs)

        if result.get("needs_escalation"):
            return {
                "response": "This request requires human assistance. A support agent will review your case shortly.",
                "escalated": True,
                "reason": result.get("escalation_reason", "Requires manual review"),
                "confidence": result.get("confidence", 0.0),
                "citations": result.get("citations", [])
            }

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