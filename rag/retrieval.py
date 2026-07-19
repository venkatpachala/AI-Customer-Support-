import os
from typing import List, Dict, Optional
from dotenv import load_dotenv

from langchain_openai import OpenAIEmbeddings
from langchain_ollama import ChatOllama
from langchain_pinecone import PineconeVectorStore
from langchain_core.documents import Document

load_dotenv()


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

    def retrieve(
        self,
        query: str,
        k: int = 8,
        final_k: int = 4,
        metadata_filter: Optional[Dict] = None
    ) -> List[Document]:
        """
        Production-style retrieval:
        Dense retrieval -> Score sorting -> Top-K selection -> Citations
        """

        print(f"\nAdvanced RAG Query: {query}")

        try:
            # Stage 1: Dense Retrieval
            results = self.vectorstore.similarity_search_with_score(
                query,
                k=k,
                filter=metadata_filter
            )

            if not results:
                print("No documents found in Pinecone")
                return []

            print(f"Dense retrieval returned {len(results)} candidates")

            # Stage 2: Attach scores and sort
            scored_docs = []
            for doc, score in results:
                doc.metadata["dense_score"] = float(score)
                scored_docs.append(doc)

            scored_docs = sorted(
                scored_docs,
                key=lambda x: x.metadata["dense_score"],
                reverse=True
            )

            # Logging
            for i, doc in enumerate(scored_docs[:6]):
                score = doc.metadata["dense_score"]
                preview = doc.page_content[:100].replace("\n", " ")
                print(f"  [{i+1}] Score: {score:.4f} | {preview}...")

            # Stage 3: Take top-k
            final_docs = scored_docs[:final_k]

            # Stage 4: Add citations
            for i, doc in enumerate(final_docs):
                source = doc.metadata.get("source", "Zepto_Terms_of_Use.pdf")
                doc.metadata["citation"] = f"{source}#chunk-{i}"

            print(f"Final documents selected: {len(final_docs)}")
            return final_docs

        except Exception as e:
            print(f"Retrieval error: {e}")
            return []

    def retrieve_with_scores(self, query: str, k: int = 8) -> List[tuple]:
        """
        Debug helper - returns documents with raw scores
        """
        results = self.vectorstore.similarity_search_with_score(query, k=k)

        print("\n=== Retrieval Diagnostics ===")
        print(f"Query: {query}")
        print("-" * 50)

        for i, (doc, score) in enumerate(results):
            print(f"[{i+1}] Score: {score:.4f}")
            print(f"     Source: {doc.metadata.get('source')}")
            print(f"     Content: {doc.page_content[:150]}...")
            print()

        return results

    def add_documents(self, docs: List[Document], namespace: str = ""):
        """Ingestion helper"""
        self.vectorstore.add_documents(docs, namespace=namespace)
        print(f"Added {len(docs)} documents to Pinecone")