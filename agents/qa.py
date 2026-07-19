from langchain_ollama import ChatOllama
from orchestration.state import AgentState
from common.messages import get_last_user_message
from typing import Dict

def qa_node(state: AgentState) -> Dict:
    query = get_last_user_message(state.get("messages", []))

    # 1. Retrieve policy documents
    from rag.retrieval import AdvancedRAGRetriever
    rag = AdvancedRAGRetriever()
    docs = rag.retrieve(query, min_score=0.45)

    if docs:
        context = "\n\n".join(doc.page_content for doc in docs)
        citations = [doc.metadata.get("citation", "N/A") for doc in docs]
    else:
        context = "No relevant policy information was found."
        citations = []

    # 2. Format tool results cleanly
    tool_results = state.get("tool_results") or {}
    if tool_results:
        tool_lines = []
        for name, result in tool_results.items():
            if isinstance(result, dict):
                status = result.get("status", "unknown")
                data = result.get("data", {})
                tool_lines.append(f"- {name}: {status} → {data}")
            else:
                tool_lines.append(f"- {name}: {result}")
        tool_context = "\n".join(tool_lines)
    else:
        tool_context = "No tools were executed."

    print(f"DEBUG: Retrieved {len(docs)} documents | Tools: {list(tool_results.keys())}")

    # 3. Very strict prompt
    prompt = f"""You are a professional Zepto customer support agent.

STRICT RULES (must follow):
1. Only use information present in the POLICY CONTEXT and TOOL RESULTS below.
2. Do NOT invent any refund amounts, currency, timelines, or policy rules.
3. If a specific amount is not mentioned in the tool results, do not invent one.
4. If policy information is missing, clearly say so and ask for more details.
5. Be honest, clear, and helpful.

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

Write a natural, professional customer support reply based ONLY on the information above:"""

    llm = ChatOllama(
        model="qwen2.5:7b",
        base_url="http://127.0.0.1:11434",
        temperature=0.3
    )

    response = llm.invoke(prompt)

    return {
        "messages": [response],
        "citations": citations,
        "confidence": 0.9 if docs else 0.5
    }