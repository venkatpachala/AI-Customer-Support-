import os
from typing import List, Dict, Optional
from dotenv import load_dotenv

from langchain_openai import OpenAIEmbeddings
from langchain_ollama import ChatOllama
from langchain_pinecone import PineconeVectorStore
from langchain_core.documents import Document

from rag.hybrid import BM25Index, reciprocal_rank_fusion

load_dotenv()


def build_citation(doc: Document) -> str:
    source = doc.metadata.get("source", "Zepto Terms of Use")
    page = doc.metadata.get("page")
    clause = doc.metadata.get("clause")
    section = doc.metadata.get("section")

    parts = [source]

    if page:
        parts.append(f"Page {page}")

    if clause:
        parts.append(f"Clause {clause}")
    elif section:
        parts.append(section)

    return ", ".join(parts)


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

        # BM25 is optional and loaded lazily
        self.bm25_index: Optional[BM25Index] = None

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
        use_hybrid: bool = True
    ) -> List[Document]:
        print(f"\nAdvanced RAG Query: {query}")
        print(f"Hybrid search: {use_hybrid}")

        try:
            # -------- Dense retrieval --------
            dense_raw = self.vectorstore.similarity_search_with_score(
                query,
                k=k,
                filter=metadata_filter
            )

            dense_results = []
            for doc, score in dense_raw:
                doc.metadata["dense_score"] = float(score)
                dense_results.append((doc, float(score)))

            print(f"Dense results: {len(dense_results)}")

            # -------- Sparse retrieval --------
            sparse_results = []
            if use_hybrid and self.bm25_index is not None:
                sparse_results = self.bm25_index.search(query, k=k)
                print(f"Sparse results: {len(sparse_results)}")

            # -------- Fusion --------
            if use_hybrid and sparse_results:
                final_docs = reciprocal_rank_fusion(
                    dense_results,
                    sparse_results,
                    k=final_k
                )
                print("Used Reciprocal Rank Fusion")
            else:
                # fallback to dense only
                dense_sorted = sorted(
                    dense_results,
                    key=lambda x: x[1],
                    reverse=True
                )
                final_docs = [doc for doc, _ in dense_sorted[:final_k]]
                print("Used dense-only retrieval")

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