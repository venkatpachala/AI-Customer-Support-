from typing import List
from langchain_core.documents import Document
from langchain_ollama import ChatOllama

class SimpleReranker:
    def __init__(self):
        self.llm = ChatOllama(
            model="qwen2.5:7b",
            base_url="http://127.0.0.1:11434",
            temperature=0
        )

    def rerank(self, query: str, documents: List[Document], top_k: int = 4) -> List[Document]:
        """
        Simple relevance reranking using the LLM
        """
        if not documents:
            return []

        scored = []

        for doc in documents:
            prompt = f"""Rate how relevant this document is to the user query.
Score from 0 to 10. Only return the number.

Query: {query}

Document:
{doc.page_content[:600]}

Relevance score:"""

            try:
                response = self.llm.invoke(prompt)
                score_text = response.content.strip()
                score = float(score_text) if score_text.replace(".", "").isdigit() else 5.0
            except Exception:
                score = 5.0

            doc.metadata["rerank_score"] = score
            scored.append(doc)

        # Sort by rerank score
        scored = sorted(scored, key=lambda x: x.metadata.get("rerank_score", 0), reverse=True)

        return scored[:top_k]from typing import List
from langchain_core.documents import Document
from langchain_ollama import ChatOllama

class SimpleReranker:
    def __init__(self):
        self.llm = ChatOllama(
            model="qwen2.5:7b",
            base_url="http://127.0.0.1:11434",
            temperature=0
        )

    def rerank(self, query: str, documents: List[Document], top_k: int = 4) -> List[Document]:
        """
        Simple relevance reranking using the LLM
        """
        if not documents:
            return []

        scored = []

        for doc in documents:
            prompt = f"""Rate how relevant this document is to the user query.
Score from 0 to 10. Only return the number.

Query: {query}

Document:
{doc.page_content[:600]}

Relevance score:"""

            try:
                response = self.llm.invoke(prompt)
                score_text = response.content.strip()
                score = float(score_text) if score_text.replace(".", "").isdigit() else 5.0
            except Exception:
                score = 5.0

            doc.metadata["rerank_score"] = score
            scored.append(doc)

        # Sort by rerank score
        scored = sorted(scored, key=lambda x: x.metadata.get("rerank_score", 0), reverse=True)

        return scored[:top_k]