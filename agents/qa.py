from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from orchestration.state import AgentState
from common.messages import get_last_user_message
from typing import Dict

# def get_llm(use_ollama: bool = True):
#     if use_ollama:
#         return ChatOpenAI(model="gpt-4o-mini", temperature=0.7)
#     else:
#         return ChatOllama(model="qwen2.5:7b", temperature=0.7)

def qa_node(state: AgentState) -> Dict:
    query = get_last_user_message(state.get("messages", []))
    
    from rag.retrieval import AdvancedRAGRetriever
    rag = AdvancedRAGRetriever()
    docs = rag.retrieve(query, min_score=0.6)  # Lower threshold for testing
    
    context = "\n\n".join([doc.page_content for doc in docs])
    citations = [doc.metadata.get("citation", "N/A") for doc in docs]
    
    print(f"DEBUG: Retrieved {len(docs)} documents")  # Add this for debug
    
    prompt = f"""Use the context below to answer accurately.

Context:
{context or "No relevant information found."}

Question: {query}

Answer based on the context if available."""

    llm = ChatOllama(model="qwen2.5:7b", temperature=0.7)
    response = llm.invoke(prompt)
    
    return {
        "messages": [response],
        "citations": citations,
        "confidence": 0.9 if docs else 0.5
    }
