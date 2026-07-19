import time
from langchain_ollama import ChatOllama
from orchestration.state import AgentState
from common.messages import get_last_user_message
from observability.logging import log_event
from observability.metrics import RAG_COUNT, NODE_LATENCY
from typing import Dict

def qa_node(state: AgentState) -> Dict:
    request_id = state.get("request_id", "unknown")
    tenant_id = state.get("tenant_id", "unknown")
    start_time = time.time()

    log_event("qa_started", request_id, node="qa")

    query = get_last_user_message(state.get("messages", []))

    # RAG retrieval
    from rag.retrieval import AdvancedRAGRetriever
    rag = AdvancedRAGRetriever()
    docs = rag.retrieve(query, k=8, final_k=4)

    if docs:
        context = "\n\n".join([doc.page_content for doc in docs])
        citations = [doc.metadata.get("citation", "N/A") for doc in docs]
        RAG_COUNT.labels(tenant_id=tenant_id, status="hit").inc()
    else:
        context = "No relevant policy information was found."
        citations = []
        RAG_COUNT.labels(tenant_id=tenant_id, status="miss").inc()

    # Tool results
    tool_results = state.get("tool_results") or {}
    if tool_results:
        tool_lines = []
        for name, result in tool_results.items():
            if isinstance(result, dict):
                status = result.get("status", "unknown")
                data = result.get("data", {})
                tool_lines.append(f"- {name}: status={status}, data={data}")
            else:
                tool_lines.append(f"- {name}: {result}")
        tool_context = "\n".join(tool_lines)
    else:
        tool_context = "No tools were executed."

    # Brand config
    tenant_config = state.get("tenant_config") or {}
    brand = tenant_config.get("brand", {})
    brand_name = brand.get("brand_name", "our company")
    tone = brand.get("tone", "professional, polite, and helpful")
    missing_photos = state.get("missing_photos", False)

    extra_instruction = ""
    if missing_photos:
        extra_instruction = """
IMPORTANT:
The return cannot be fully processed yet because photos of the damaged product are required.
Politely ask the customer to share clear photos of the damage.
Do not invent any return label or shipping steps.
"""

    prompt = f"""You are a customer support agent for {brand_name}.
Tone: {tone}

STRICT RULES:
1. Only use information present in the POLICY CONTEXT and TOOL RESULTS.
2. Never invent return labels, addresses, refund amounts, or timelines.
3. Only mention actions that actually appear in the TOOL RESULTS.
4. If photos are required, clearly ask for them.

{extra_instruction}

------------------------
POLICY CONTEXT
------------------------
{context}

------------------------
TOOL RESULTS
------------------------
{tool_context}

------------------------
CUSTOMER QUESTION
------------------------
{query}

Write a clear and professional reply:"""

    llm = ChatOllama(
        model="qwen2.5:7b",
        base_url="http://127.0.0.1:11434",
        temperature=0.15
    )

    response = llm.invoke(prompt)

    duration = time.time() - start_time
    NODE_LATENCY.labels(node="qa").observe(duration)

    log_event("qa_completed", request_id, node="qa", data={
        "docs_retrieved": len(docs),
        "citations": citations,
        "missing_photos": missing_photos,
        "duration": round(duration, 3)
    })

    return {
        "messages": [response],
        "citations": citations,
        "confidence": 0.9 if docs else 0.5
    }