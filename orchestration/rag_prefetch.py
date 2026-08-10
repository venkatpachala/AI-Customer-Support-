from typing import Dict, Any
from common.messages import get_last_user_message
from observability.logging import log_event


def rag_prefetch_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Runs in parallel with supervisor.
    Prefetches policy docs so QA can skip retrieval when available.
    """
    request_id = state.get("request_id", "unknown")
    log_event("rag_prefetch_started", request_id, node="rag_prefetch")

    try:
        query = get_last_user_message(state.get("messages", []))
        if not query:
            return {
                "prefetched_docs": [],
                "prefetched_citations": [],
                "rag_prefetched": True,
            }

        from agents.qa import get_rag  # reuse existing singleton
        rag = get_rag()

        # smaller retrieve for speed; QA can still work with this
        docs = rag.retrieve(query, k=6, final_k=3, use_hybrid=True)

        citations = []
        serializable_docs = []
        for doc in docs or []:
            citations.append(doc.metadata.get("citation", "N/A"))
            serializable_docs.append({
                "page_content": doc.page_content,
                "metadata": dict(doc.metadata or {}),
            })

        log_event(
            "rag_prefetch_completed",
            request_id,
            node="rag_prefetch",
            data={"docs": len(serializable_docs)},
        )

        return {
            "prefetched_docs": serializable_docs,
            "prefetched_citations": citations,
            "rag_prefetched": True,
        }

    except Exception as e:
        log_event(
            "rag_prefetch_failed",
            request_id,
            node="rag_prefetch",
            data={"error": str(e)},
            level="warning",
        )
        return {
            "prefetched_docs": [],
            "prefetched_citations": [],
            "rag_prefetched": True,
        }