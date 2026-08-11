import os
import re
import hashlib
from typing import List, Dict, Optional, Tuple

from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from langchain_ollama import ChatOllama
from langchain_pinecone import PineconeVectorStore
from langchain_core.documents import Document

from rag.hybrid import BM25Index, reciprocal_rank_fusion
from rag.reranker import SimpleReranker

load_dotenv()


def build_citation(doc: Document) -> str:
    source = doc.metadata.get("source", "Zepto Terms of Use")
    page = doc.metadata.get("page")
    clause = doc.metadata.get("clause")
    section = doc.metadata.get("section")

    parts = [source]

    if page is not None and page != "":
        parts.append(f"Page {page}")

    if clause:
        parts.append(f"Clause {clause}")
    elif section:
        parts.append(str(section))

    return ", ".join(parts)


def _norm_text(text: str, n: int = 300) -> str:
    t = re.sub(r"\s+", " ", (text or "").lower()).strip()
    return t[:n]


def dedup_docs(docs: List[Document]) -> List[Document]:
    """
    Collapse near-identical chunks using stable identity.
    Prefer source_id + clause + normalized content.
    """
    seen = set()
    unique: List[Document] = []

    for doc in docs:
        md = doc.metadata or {}
        source_id = md.get("source_id") or md.get("source") or ""
        clause = str(md.get("clause") or "").strip()
        page = str(md.get("page") or "")
        content_key = _norm_text(doc.page_content, n=400)

        # primary identity
        if clause:
            key = f"{source_id}|{clause}|{content_key[:160]}"
        else:
            key = f"{source_id}|p{page}|{content_key[:200]}"

        sig = hashlib.md5(key.encode("utf-8")).hexdigest()
        if sig in seen:
            continue
        seen.add(sig)
        unique.append(doc)

    return unique


class AdvancedRAGRetriever:
    def __init__(self):
        self.embeddings = OpenAIEmbeddings(
            model="text-embedding-3-large"
        )

        self.llm = ChatOllama(
            model="qwen2.5:7b",
            base_url="http://127.0.0.1:11434",
            temperature=0
        )

        self.vectorstore = PineconeVectorStore(
            index_name=os.getenv("PINECONE_INDEX_NAME"),
            embedding=self.embeddings
        )

        self.bm25_index: Optional[BM25Index] = None
        self.reranker = SimpleReranker()

    def load_bm25_documents(self, documents: List[Document]):
        """
        Call this after ingestion / at startup with the same chunks
        used for Pinecone.
        """
        self.bm25_index = BM25Index(documents)
        print(f"BM25 index loaded with {len(documents)} documents")

    def retrieve(
        self,
        query: str,
        k: int = 8,
        final_k: int = 4,
        metadata_filter: Optional[Dict] = None,
        use_hybrid: bool = True,
        use_rerank: bool = True,
    ) -> List[Document]:
        print(f"\nAdvanced RAG Query: {query}")
        print(f"Hybrid search: {use_hybrid} | Rerank: {use_rerank}")

        try:
            # Pull extra candidates so dedup + rerank still leave enough
            candidate_k = max(k, final_k * 3, 8)

            # -------- Dense retrieval --------
            dense_raw = self.vectorstore.similarity_search_with_score(
                query,
                k=candidate_k,
                filter=metadata_filter
            )

            dense_results: List[Tuple[Document, float]] = []
            for doc, score in dense_raw:
                # copy metadata to avoid accidental shared mutation issues
                doc.metadata = dict(doc.metadata or {})
                doc.metadata["dense_score"] = float(score)
                dense_results.append((doc, float(score)))

            print(f"Dense results: {len(dense_results)}")

            # -------- Sparse retrieval --------
            sparse_results: List[Tuple[Document, float]] = []
            if use_hybrid and self.bm25_index is not None:
                sparse_results = self.bm25_index.search(query, k=candidate_k)
                print(f"Sparse results: {len(sparse_results)}")
            elif use_hybrid and self.bm25_index is None:
                print("Hybrid requested but BM25 index is not loaded")

            # -------- Fusion / ranking --------
            if use_hybrid and sparse_results:
                ranked_docs = reciprocal_rank_fusion(
                    dense_results,
                    sparse_results,
                    k=candidate_k
                )
                print("Used Reciprocal Rank Fusion")
            else:
                dense_sorted = sorted(
                    dense_results,
                    key=lambda x: x[1],
                    reverse=True
                )
                ranked_docs = [doc for doc, _ in dense_sorted]
                print("Used dense-only retrieval")

            # -------- Deduplicate while preserving rank --------
            before = len(ranked_docs)
            ranked_docs = dedup_docs(ranked_docs)
            removed = before - len(ranked_docs)
            if removed > 0:
                print(f"Dedup removed {removed} near-duplicate chunks")

            # -------- Rerank --------
            if use_rerank and len(ranked_docs) > 1:
                rerank_pool = ranked_docs[: max(8, final_k * 2)]
                print(f"Reranking {len(rerank_pool)} candidates")
                final_docs = self.reranker.rerank(
                    query=query,
                    documents=rerank_pool,
                    top_k=final_k
                )
            else:
                final_docs = ranked_docs[:final_k]

            # -------- Citations --------
            for doc in final_docs:
                doc.metadata["citation"] = build_citation(doc)

            print(f"Final documents: {len(final_docs)}")
            for i, doc in enumerate(final_docs):
                print(
                    f"  [{i+1}] {doc.metadata.get('citation')} | "
                    f"{doc.page_content[:80].replace(chr(10), ' ')}..."
                )

            return final_docs

        except Exception as e:
            print(f"Retrieval error: {e}")
            return []

    def retrieve_with_scores(self, query: str, k: int = 8):
        results = self.vectorstore.similarity_search_with_score(query, k=k)
        print("\n=== Dense Retrieval Diagnostics ===")
        for i, (doc, score) in enumerate(results):
            print(f"[{i+1}] Score: {score:.4f}")
            print(f"     Citation: {build_citation(doc)}")
            print(f"     Content : {doc.page_content[:140]}...")
            print()
        return results

    def add_documents(self, docs: List[Document], namespace: str = ""):
        self.vectorstore.add_documents(docs, namespace=namespace)
        print(f"Added {len(docs)} documents to Pinecone")