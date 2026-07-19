from langchain_ollama import ChatOllama
from orchestration.state import AgentState
from common.messages import get_last_user_message
from typing import Dict

def qa_node(state: AgentState) -> Dict:
    query = get_last_user_message(state.get("messages", []))

    # 1. Retrieve policy documents
    from rag.retrieval import AdvancedRAGRetriever
    rag = AdvancedRAGRetriever()
    docs = rag.retrieve(query, k=8, final_k=4)

    if docs:
        context = "\n\n".join([doc.page_content for doc in docs])
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
                tool_lines.append(f"- {name}: status={status}, data={data}")
            else:
                tool_lines.append(f"- {name}: {result}")
        tool_context = "\n".join(tool_lines)
    else:
        tool_context = "No tools were executed."

    print(f"DEBUG: Retrieved {len(docs)} documents | Tools: {list(tool_results.keys())}")

    # 3. Strict grounded prompt
    prompt = f"""You are a customer support agent for Zepto.

You must follow these rules without exception:

1. You can ONLY use information that is explicitly present in the POLICY CONTEXT and TOOL RESULTS below.
2. You are NOT allowed to invent:
   - Return labels
   - Shipping addresses
   - Email confirmations
   - Refund amounts
   - Timelines
   - Replacement processes
   - Any step that is not present in the tool results or policy
3. If the policy requires the customer to provide photos or additional information, clearly ask for it.
4. If the policy context is empty or insufficient, clearly say that you do not have enough policy information to answer fully.
5. Only mention actions that actually appear in the TOOL RESULTS.
6. Stay strictly within Zepto company policies. Do not give general e-commerce advice.

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

Write a clear, factual, and professional reply based only on the information above.
If you cannot answer properly due to missing information, say so."""

    llm = ChatOllama(
        model="qwen2.5:7b",
        base_url="http://127.0.0.1:11434",
        temperature=0.2
    )

    response = llm.invoke(prompt)

    return {
        "messages": [response],
        "citations": citations,
        "confidence": 0.9 if docs else 0.5
    }