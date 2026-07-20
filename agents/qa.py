import time
from pathlib import Path
import pickle
from typing import Dict

from langchain_ollama import ChatOllama
from orchestration.state import AgentState
from common.messages import get_last_user_message
from observability.logging import log_event
from observability.metrics import RAG_COUNT, NODE_LATENCY

_rag_instance = None

def get_rag():
    global _rag_instance
    if _rag_instance is None:
        from rag.retrieval import AdvancedRAGRetriever
        _rag_instance = AdvancedRAGRetriever()
        bm25_path = Path("rag/bm25_corpus.pkl")
        if bm25_path.exists():
            with open(bm25_path, "rb") as f:
                bm25_docs = pickle.load(f)
            _rag_instance.load_bm25_documents(bm25_docs)
    return _rag_instance


def qa_node(state: AgentState) -> Dict:
    request_id = state.get("request_id", "unknown")
    tenant_id = state.get("tenant_id", "unknown")
    start_time = time.time()

    log_event("qa_started", request_id, node="qa")

    query = get_last_user_message(state.get("messages", []))
    memory_context = state.get("memory_context") or {}

    # RAG
    rag = get_rag()
    docs = rag.retrieve(query, k=8, final_k=4, use_hybrid=True)

    if docs:
        context = "\n\n".join([doc.page_content for doc in docs])
        citations = [doc.metadata.get("citation", "N/A") for doc in docs]
        RAG_COUNT.labels(tenant_id=tenant_id, status="hit").inc()
    else:
        context = "No relevant policy information was found."
        citations = []
        RAG_COUNT.labels(tenant_id=tenant_id, status="miss").inc()

    # Tools
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

    # Brand
    tenant_config = state.get("tenant_config") or {}
    brand = tenant_config.get("brand", {})
    brand_name = brand.get("brand_name", "our company")
    tone = brand.get("tone", "professional, polite, and helpful")

    active_order_id = memory_context.get("active_order_id")
    missing_inputs = memory_context.get("missing_inputs") or []
    photos_requested = memory_context.get("photos_requested", False)
    photos_received = memory_context.get("photos_received", False)
    case_status = memory_context.get("case_status")

    extra_instruction = ""
    if ("photos" in missing_inputs or photos_requested) and not photos_received:
        extra_instruction = f"""
IMPORTANT:
Photos are still required to continue the return/refund process.
Ask politely for clear photos of the damaged product.
If order ID is known ({active_order_id}), mention it.
Do not invent return labels or shipping steps.
"""

    recent_messages = memory_context.get("recent_messages") or []
    history_text = "\n".join(
        [f"{m.get('role')}: {m.get('content')}" for m in recent_messages[-4:]]
    ) or "No prior messages."

    prompt = f"""You are a customer support agent for {brand_name}.
Tone: {tone}

STRICT RULES:
1. Only use POLICY CONTEXT, TOOL RESULTS, and MEMORY.
2. Never invent return labels, addresses, refund amounts, or timelines.
3. Do not re-ask for information already present in memory.
4. If photos are required and not received, ask for photos.
5. If case_status is escalated, inform the user that a human agent will review.

MEMORY:
- active_order_id: {active_order_id}
- missing_inputs: {missing_inputs}
- photos_requested: {photos_requested}
- photos_received: {photos_received}
- case_status: {case_status}

RECENT CONVERSATION:
{history_text}

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
        "missing_inputs": missing_inputs,
        "active_order_id": active_order_id,
        "duration": round(duration, 3)
    })

    return {
        "messages": [response],
        "citations": citations,
        "confidence": 0.9 if docs else 0.5
    }