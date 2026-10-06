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
from rag.tenant_filter import is_duplicate_source, select_tenant_docs


def _legacy_zepto_source(metadata: Dict) -> bool:
    """Pre-tenant index rows for the canonical Zepto terms. Paths and other brands stay out."""
    source = str((metadata or {}).get("source") or "").strip()
    source_id = str((metadata or {}).get("source_id") or "").strip()
    if is_duplicate_source(source):
        return False
    if source_id.startswith("zepto_terms"):
        return True
    return source in {"Zepto Terms of Use", "Zepto"}

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


def _scope_pairs(
    pairs: List[Tuple[Document, float]],
    tenant_id: str,
    snapshot_id: str = "",
) -> List[Tuple[Document, float]]:
    scoped: List[Tuple[Document, float]] = []
    snapshot = str(snapshot_id or "").strip()
    for doc, score in pairs:
        metadata = doc.metadata or {}
        if is_duplicate_source(metadata.get("source")):
            continue
        if tenant_id and str(metadata.get("tenant_id") or "") != tenant_id:
            continue
        if snapshot and str(metadata.get("knowledge_snapshot") or "") != snapshot:
            continue
        scoped.append((doc, score))
    return scoped


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
        self.last_retrieval = {
            "hybrid": bool(use_hybrid),
            "fusion": "dense_only",
            "dense_n": 0,
            "sparse_n": 0,
        }

        try:
            # Pull extra candidates so dedup + rerank still leave enough
            candidate_k = max(k, final_k * 3, 8)

            # -------- Dense retrieval --------
            dense_raw = self.vectorstore.similarity_search_with_score(
                query,
                k=candidate_k,
                filter=metadata_filter
            )
            tenant_id = str((metadata_filter or {}).get("tenant_id") or "").strip()
            if not dense_raw and tenant_id == "zepto":
                # The August index has clause metadata and no tenant_id. Do not borrow another brand.
                print("Dense tenant filter empty; loading legacy Zepto terms vectors")
                dense_raw = self.vectorstore.similarity_search_with_score(query, k=candidate_k)

            dense_results: List[Tuple[Document, float]] = []
            for doc, score in dense_raw:
                # copy metadata to avoid accidental shared mutation issues
                doc.metadata = dict(doc.metadata or {})
                existing = str(doc.metadata.get("tenant_id") or "").strip()
                if tenant_id and existing and existing != tenant_id:
                    continue
                if tenant_id == "zepto" and not existing:
                    if not _legacy_zepto_source(doc.metadata):
                        continue
                    doc.metadata["tenant_id"] = "zepto"
                doc.metadata["dense_score"] = float(score)
                dense_results.append((doc, float(score)))

            print(f"Dense results: {len(dense_results)}")
            tenant_id = str((metadata_filter or {}).get("tenant_id") or "").strip()
            snapshot_id = str((metadata_filter or {}).get("knowledge_snapshot") or "").strip()
            dense_results = _scope_pairs(dense_results, tenant_id, snapshot_id)
            self.last_retrieval["dense_n"] = len(dense_results)

            # -------- Sparse retrieval --------
            sparse_results: List[Tuple[Document, float]] = []
            if use_hybrid and self.bm25_index is not None:
                sparse_results = _scope_pairs(
                    self.bm25_index.search(query, k=candidate_k),
                    tenant_id,
                    snapshot_id,
                )
                print(f"Sparse results: {len(sparse_results)}")
            elif use_hybrid and self.bm25_index is None:
                print("Hybrid requested but BM25 index is not loaded")
            self.last_retrieval["sparse_n"] = len(sparse_results)

            # -------- Fusion / ranking --------
            if use_hybrid and sparse_results:
                ranked_docs = reciprocal_rank_fusion(
                    dense_results,
                    sparse_results,
                    k=candidate_k
                )
                self.last_retrieval["fusion"] = "rrf"
                print("Used Reciprocal Rank Fusion")
            else:
                dense_sorted = sorted(
                    dense_results,
                    key=lambda x: x[1],
                    reverse=True
                )
                ranked_docs = [doc for doc, _ in dense_sorted]
                print("Used dense-only retrieval")

            if tenant_id and not ranked_docs:
                print(f"No chunks for tenant {tenant_id}")
                return []

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

            if tenant_id:
                final_docs = select_tenant_docs(final_docs, tenant_id, snapshot_id or None)
            print(f"Final documents: {len(final_docs)}")
            for i, doc in enumerate(final_docs):
                print(
                    f"  [{i+1}] {doc.metadata.get('citation')} | "
                    f"{doc.page_content[:80].replace(chr(10), ' ')}..."
                )

            return final_docs

        except Exception as e:
            print(f"Retrieval error: {e}")
            self.last_retrieval["fusion"] = "error"
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