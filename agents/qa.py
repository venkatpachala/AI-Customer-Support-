from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from orchestration.state import AgentState
from common.messages import get_last_user_message
from typing import Dict

def get_llm(use_gpt: bool = True):
    if use_gpt:
        return ChatOpenAI(model="gpt-4o-mini", temperature=0.7)
    else:
        return ChatOllama(model="qwen2.5:7b", temperature=0.7)

def qa_node(state: AgentState) -> Dict:
    query = get_last_user_message(state.get("messages", []))
    
    # RAG
    from rag.retrieval import AdvancedRAGRetriever
    rag = AdvancedRAGRetriever()
    docs = rag.retrieve(query)
    
    context = "\n\n".join([doc.page_content for doc in docs])
    citations = [doc.metadata.get("citation", "N/A") for doc in docs]
    
    prompt = f"""Context:
{context}

Question: {query}

Answer professionally and cite sources if possible."""

    llm = get_llm(use_gpt=True)
    response = llm.invoke(prompt)
    
    return {
        "messages": [response],  # Let LangGraph handle it as BaseMessage
        "citations": citations,
        "confidence": 0.85 if docs else 0.6
    }