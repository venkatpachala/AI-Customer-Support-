import os
import re
import json
from typing import List, Optional

from langchain_core.documents import Document
from langchain_openai import ChatOpenAI


def _extract_json_array(text: str) -> list:
    text = (text or "").strip()
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except Exception:
        pass

    match = re.search(r"\[[\s\S]*\]", text)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, list) else []
    except Exception:
        return []


class SimpleReranker:
    """
    Listwise reranker: one LLM call ranks all candidates.
    Compatible method: rerank(query, documents, top_k)
    """

    def __init__(self, model: Optional[str] = None):
        self.model = model or os.getenv("RERANK_MODEL", os.getenv("QA_MODEL", "gpt-4o-mini"))
        self.llm = ChatOpenAI(
            model=self.model,
            temperature=0,
            api_key=os.getenv("OPENAI_API_KEY"),
        )

    def rerank(self, query: str, documents: List[Document], top_k: int = 4) -> List[Document]:
        if not documents:
            return []
        if len(documents) == 1:
            return documents[:top_k]

        numbered = []
        for i, doc in enumerate(documents):
            md = doc.metadata or {}
            clause = md.get("clause") or ""
            page = md.get("page") or ""
            preview = re.sub(r"\s+", " ", doc.page_content or "").strip()[:500]
            numbered.append(f"[{i}] clause={clause} page={page}\n{preview}")

        prompt = f"""You are a retrieval reranker for policy documents.
Rank candidates from most relevant to least relevant for the question.

Return ONLY a JSON array of indices best-to-worst.
Example: [2, 0, 4, 1, 3]

Question:
{query}

Candidates:
{chr(10).join(numbered)}
"""

        try:
            raw = self.llm.invoke(prompt)
            content = raw.content if hasattr(raw, "content") else str(raw)
            order = _extract_json_array(content)
        except Exception:
            order = []

        used = set()
        ranked: List[Document] = []

        for idx in order:
            try:
                i = int(idx)
            except Exception:
                continue
            if 0 <= i < len(documents) and i not in used:
                documents[i].metadata["rerank_rank"] = len(ranked) + 1
                ranked.append(documents[i])
                used.add(i)

        # keep any missing docs in original order
        for i, doc in enumerate(documents):
            if i not in used:
                doc.metadata["rerank_rank"] = len(ranked) + 1
                ranked.append(doc)

        return ranked[:top_k]


def rerank_documents(query: str, docs: List[Document], top_n: Optional[int] = None) -> List[Document]:
    """Functional helper used by retrieval.py"""
    top_n = top_n or len(docs)
    return SimpleReranker().rerank(query, docs, top_k=top_n)