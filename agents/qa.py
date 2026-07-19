from langchain_ollama import ChatOllama
from orchestration.state import AgentState
from common.messages import get_last_user_message
from typing import Dict

def qa_node(state: AgentState) -> Dict:
    query = get_last_user_message(state.get("messages", []))

    # 1. Retrieve policy documents
    from rag.retrieval import AdvancedRAGRetriever
    rag = AdvancedRAGRetriever()
    docs = rag.retrieve(query, min_score=0.6)

    if docs:
        context = "\n\n".join(doc.page_content for doc in docs)
        citations = [doc.metadata.get("source", "N/A") for doc in docs]
    else:
        context = "No relevant policy found."
        citations = []

    tool_results = state.get("tool_results") or {}
    
    if tool_results:
        tool_lines = []
        for tool_name, result in tool_results.items():
            status = result.get("status", "unknown") if isinstance(result, dict) else "success"
            data = result.get("data", result) if isinstance(result, dict) else result
            tool_lines.append(f"- {tool_name}: status={status}, data={data}")
        tool_context = "\n".join(tool_lines)
    else:
        tool_context = "No tools were executed."

    print(f"DEBUG: Retrieved {len(docs)} documents | Tools: {list(tool_results.keys())}")

    # 3. Improved prompt for better response quality
    prompt = f"""You are a polite and professional Zepto customer support agent.

POLICY CONTEXT:
{context}

TOOL RESULTS:
{tool_context}

CUSTOMER MESSAGE:
{query}

Guidelines:
1. Acknowledge the customer's issue with empathy.
2. Clearly mention what actions have already been taken (based on tool results).
3. Explain the next steps the customer needs to complete.
4. If photos are required according to policy, politely ask for them.
5. Do not invent any rules that are not in the policy.
6. Keep the tone helpful, clear and professional.

Write a natural customer support reply:"""

    llm = ChatOllama(model="qwen2.5:7b", temperature=0.6)
    response = llm.invoke(prompt)

    return {
        "messages": [response],
        "citations": citations,
        "confidence": 0.9 if docs else 0.5,
    }