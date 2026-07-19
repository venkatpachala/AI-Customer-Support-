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
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
        
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
        metadata_filter: Optional[Dict] = None,
        min_score: float = 0.45,
        k: int = 6
    ) -> List[Document]:
        """Reliable retrieval with good logging"""
        
        print(f"\n RAG Query: {query}")

        try:
            results = self.vectorstore.similarity_search_with_score(
                query,
                k=k,
                filter=metadata_filter
            )

            print(f"Pinecone returned {len(results)} candidates")

            filtered_docs = []
            for doc, score in results:
                print(f"  → Score: {score:.4f} | {doc.metadata.get('source')} | {doc.page_content[:100]}...")
                if score >= min_score:
                    filtered_docs.append(doc)

            print(f"Final documents after filter (min_score={min_score}): {len(filtered_docs)}")

            # Add citations
            for i, doc in enumerate(filtered_docs):
                doc.metadata["citation"] = f"{doc.metadata.get('source', 'Zepto')}#{i}"

            return filtered_docs

        except Exception as e:
            print(f"Retrieval error: {e}")
            return []

    def retrieve_with_scores(self, query: str, k: int = 6):
        """For debugging only"""
        results = self.vectorstore.similarity_search_with_score(query, k=k)
        print(f"\n=== Debug Scores for: '{query}' ===")
        for i, (doc, score) in enumerate(results):
            print(f"[{i+1}] {score:.4f} | {doc.page_content[:120]}...")
        return results