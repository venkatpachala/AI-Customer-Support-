from langchain_ollama import ChatOllama
from orchestration.state import AgentState
from common.messages import get_last_user_message
from typing import Dict

def qa_node(state: AgentState) -> Dict:
    query = get_last_user_message(state.get("messages", []))
    missing_photos = state.get("missing_photos", False)
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

    # 2. Format tool results
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

    # 3. Load brand config
    tenant_config = state.get("tenant_config") or {}
    brand = tenant_config.get("brand", {})
    brand_name = brand.get("brand_name", "our company")
    tone = brand.get("tone", "professional, polite, and helpful")

    print(f"DEBUG: Retrieved {len(docs)} documents | Tools: {list(tool_results.keys())} | Brand: {brand_name}")

    # 4. Strict grounded prompt
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
4. If photos are required, clearly ask the customer to provide them.

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

    return {
        "messages": [response],
        "citations": citations,
        "confidence": 0.9 if docs else 0.5
    }