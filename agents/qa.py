from langchain_ollama import ChatOllama
from orchestration.state import AgentState
from common.messages import get_last_user_message
from typing import Dict

def qa_node(state: AgentState) -> Dict:
    query = get_last_user_message(state.get("messages", []))

    # 1. Retrieve documents
    from rag.retrieval import AdvancedRAGRetriever
    rag = AdvancedRAGRetriever()
    docs = rag.retrieve(query, min_score=0.6)

    # 2. Build context FIRST
    if docs:
        context = "\n\n".join(doc.page_content for doc in docs)
        citations = [doc.metadata.get("source", "N/A") for doc in docs]
    else:
        context = "No relevant policy found."
        citations = []

    # 3. Collect tool results
    tool_results = state.get("tool_results") or {}
    tool_context = (
        "\n".join(f"{k}: {v}" for k, v in tool_results.items())
        if tool_results
        else "No tool results."
    )

    print(f"DEBUG: Retrieved {len(docs)} documents | Tools: {list(tool_results.keys())}")

    # 4. Create ONE clean prompt
    prompt = f"""You are a helpful Zepto customer support AI.

Use BOTH the retrieved policy and the executed tool results.

------------------------
POLICY
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

Answer according to the policy.
If the policy requires verification or photos, clearly tell the customer what is needed next.
Do not invent any policy rules."""

    # 5. Call LLM
    llm = ChatOllama(model="qwen2.5:7b", temperature=0.7)
    response = llm.invoke(prompt)

    return {
        "messages": [response],
        "citations": citations,
        "confidence": 0.9 if docs else 0.5,
    }