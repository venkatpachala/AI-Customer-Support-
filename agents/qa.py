import time
from pathlib import Path
import pickle
from typing import Dict, Any, List

from orchestration.state import AgentState
from common.messages import get_last_user_message
from observability.logging import log_event
from observability.metrics import RAG_COUNT, NODE_LATENCY
from common.llm import get_qa_llm

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


def _as_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def qa_node(state: AgentState) -> Dict:
    request_id = state.get("request_id", "unknown")
    tenant_id = state.get("tenant_id", "unknown")
    start_time = time.time()

    log_event("qa_started", request_id, node="qa")

    query = get_last_user_message(state.get("messages", []))
    memory_context = state.get("memory_context") or {}
    plan = state.get("current_plan") or {
        "intent": state.get("intent", "policy"),
        "missing_inputs": [],
    }

    # ---------------- RAG (prefer prefetched docs) ----------------
    prefetched_docs = state.get("prefetched_docs") or []
    prefetched_citations = state.get("prefetched_citations") or []
    docs = []
    used_prefetch = False

    if prefetched_docs:
        used_prefetch = True
        context = "\n\n".join([d.get("page_content", "") for d in prefetched_docs])
        citations = prefetched_citations or [
            (d.get("metadata") or {}).get("citation", "N/A") for d in prefetched_docs
        ]
        docs = prefetched_docs
        try:
            RAG_COUNT.labels(tenant_id=tenant_id, status="hit").inc()
        except Exception:
            pass
        log_event(
            "qa_using_prefetched_docs",
            request_id,
            node="qa",
            data={"docs": len(prefetched_docs)},
        )
    else:
        rag = get_rag()
        retrieved = rag.retrieve(query, k=8, final_k=4, use_hybrid=True)
        docs = retrieved or []

        if docs:
            context = "\n\n".join([doc.page_content for doc in docs])
            citations = [doc.metadata.get("citation", "N/A") for doc in docs]
            try:
                RAG_COUNT.labels(tenant_id=tenant_id, status="hit").inc()
            except Exception:
                pass
        else:
            context = "No relevant policy information was found."
            citations = []
            try:
                RAG_COUNT.labels(tenant_id=tenant_id, status="miss").inc()
            except Exception:
                pass

    # ---------------- Tools ----------------
    tool_results = state.get("tool_results") or {}
    if tool_results:
        tool_lines = []
        for name, result in tool_results.items():
            if isinstance(result, dict):
                status = result.get("status", "unknown")
                data = result.get("data", {})
                error = result.get("error")
                if status == "error":
                    tool_lines.append(f"- {name}: status={status}, error={error}")
                else:
                    tool_lines.append(f"- {name}: status={status}, data={data}")
            else:
                tool_lines.append(f"- {name}: {result}")
        tool_context = "\n".join(tool_lines)
    else:
        tool_context = "No tools were executed."

    # ---------------- Brand ----------------
    tenant_config = state.get("tenant_config") or {}
    brand = tenant_config.get("brand", {})
    brand_name = brand.get("brand_name", "our company")
    tone = brand.get("tone", "professional, polite, and helpful")

    # ---------------- Memory / flags ----------------
    active_order_id = (
        memory_context.get("active_order_id")
        or state.get("resolved_order_id")
    )
    missing_inputs = _as_list(
        memory_context.get("missing_inputs")
        or plan.get("missing_inputs")
        or []
    )
    photos_requested = bool(memory_context.get("photos_requested", False))
    photos_received = bool(memory_context.get("photos_received", False))
    case_status = memory_context.get("case_status") or "open"

    missing_photos = bool(
        state.get("missing_photos", False)
        or ("photos" in missing_inputs)
        or (photos_requested and not photos_received)
    )

    needs_escalation = bool(
        state.get("needs_escalation", False) or case_status == "escalated"
    )

    # ---------------- Instructions ----------------
    extra_instruction = ""

    if needs_escalation or case_status == "escalated":
        extra_instruction = """
IMPORTANT:
This case requires human assistance.
Tell the customer that a support agent will review the case shortly.
Do not promise refund completion, return labels, or timelines.
Do not ask for more tools to be run.
"""
    elif missing_photos and not photos_received:
        order_ref = active_order_id or "your order"
        extra_instruction = f"""
IMPORTANT:
Photos are required before we can proceed with return/refund for {order_ref}.
You must explicitly ask the customer to upload clear photos of the damaged product.
Mention the order ID if known.
Do NOT escalate.
Do NOT invent return labels, shipping addresses, pickup slots, or refund timelines.
Keep the response short and actionable.
"""
    elif "order_id" in missing_inputs and not active_order_id:
        extra_instruction = """
IMPORTANT:
Order ID is missing.
Politely ask the customer for their order ID so you can continue.
Do NOT invent order details.
"""

    recent_messages = memory_context.get("recent_messages") or []
    history_text = "\n".join(
        [f"{m.get('role')}: {m.get('content')}" for m in recent_messages[-6:]]
    ) or "No prior messages."

    prompt = f"""You are a customer support agent for {brand_name}.
Tone: {tone}

STRICT RULES:
1. Only use POLICY CONTEXT, TOOL RESULTS, and MEMORY.
2. Never invent return labels, addresses, refund amounts, pickup slots, or timelines.
3. Do not re-ask for information already present in memory.
4. If photos are required and not received, ask for photos clearly.
5. If case is escalated, tell the user a human agent will review it.
6. If tools failed due to system issues, still help with policy guidance and next required customer action.
7. Keep responses concise and operational.

MEMORY:
- active_order_id: {active_order_id}
- missing_inputs: {missing_inputs}
- photos_requested: {photos_requested}
- photos_received: {photos_received}
- missing_photos: {missing_photos}
- case_status: {case_status}
- needs_escalation: {needs_escalation}

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

    llm = get_qa_llm(temperature=0.1)
    response = llm.invoke(prompt)

    duration = time.time() - start_time
    try:
        NODE_LATENCY.labels(node="qa").observe(duration)
    except Exception:
        pass

    log_event("qa_completed", request_id, node="qa", data={
        "docs_retrieved": len(docs),
        "used_prefetch": used_prefetch,
        "citations": citations,
        "missing_inputs": missing_inputs,
        "missing_photos": missing_photos,
        "active_order_id": active_order_id,
        "case_status": case_status,
        "needs_escalation": needs_escalation,
        "duration": round(duration, 3),
    })

    return {
        "messages": [response],
        "citations": citations,
        "confidence": 0.9 if docs else 0.55,
        "missing_photos": missing_photos,
    }