from langchain_ollama import ChatOllama
from orchestration.state import AgentState
from common.messages import get_last_user_message
from typing import Dict

def qa_node(state: AgentState) -> Dict:
    query = get_last_user_message(state.get("messages", []))

    # 1. Retrieve policy
    from rag.retrieval import AdvancedRAGRetriever
    rag = AdvancedRAGRetriever()
    docs = rag.retrieve(query, min_score=0.50)

    context = "\n\n".join([doc.page_content for doc in docs]) if docs else "No relevant policy found."
    citations = [doc.metadata.get("citation", "N/A") for doc in docs]

    # 2. Clean tool results
    tool_results = state.get("tool_results") or {}
    tool_summary = []

    for tool_name, result in tool_results.items():
        if isinstance(result, dict):
            status = result.get("status", "unknown")
            data = result.get("data", {})
            tool_summary.append(f"- {tool_name}: {status} → {data}")
        else:
            tool_summary.append(f"- {tool_name}: {result}")

    tool_context = "\n".join(tool_summary) if tool_summary else "No tools were executed."

    print(f"DEBUG: Retrieved {len(docs)} documents | Tools used: {list(tool_results.keys())}")

    # 3. Strict prompt
    prompt = f"""You are a professional Zepto customer support agent.

You must answer ONLY using the information given below.
Do NOT invent any amounts, policies, or actions.

------------------------
POLICY CONTEXT
------------------------
{context}

------------------------
TOOL RESULTS (What actually happened)
------------------------
{tool_context}

------------------------
CUSTOMER QUESTION
------------------------
{query}

Instructions:
- Be polite and clear.
- Clearly state what has already been done based on the tool results.
- Tell the customer the next steps according to the policy.
- If photos are required, ask for them.
- If information is missing, say so honestly.
- Never invent refund amounts or policy rules.

Write a natural customer support reply:"""

    llm = ChatOllama(
        model="qwen2.5:7b",
        base_url="http://127.0.0.1:11434",
        temperature=0.4
    )

    response = llm.invoke(prompt)

    return {
        "messages": [response],
        "citations": citations,
        "confidence": 0.9 if docs else 0.55
    }