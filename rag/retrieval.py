import os
from typing import List, Dict, Optional
from dotenv import load_dotenv

from langchain_openai import OpenAIEmbeddings
from langchain_ollama import ChatOllama
from langchain_pinecone import PineconeVectorStore
from langchain_core.documents import Document
from langchain_classic.retrievers import ContextualCompressionRetriever
from langchain_classic.retrievers.document_compressors import LLMChainExtractor

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
        min_score: float = 0.50,
        k: int = 6,
        use_compression: bool = False   # Turn off by default for stability
    ) -> List[Document]:

        print(f"\n🔍 RAG Query: {query}")

        try:
            search_kwargs = {"k": k}
            if metadata_filter:
                search_kwargs["filter"] = metadata_filter

            # Simple + reliable retrieval first
            docs_with_scores = self.vectorstore.similarity_search_with_score(
                query, k=k, filter=metadata_filter
            )

            print(f"Raw documents retrieved: {len(docs_with_scores)}")

            # Filter by score
            filtered = []
            for doc, score in docs_with_scores:
                print(f"  Score: {score:.4f} | {doc.metadata.get('source')} | {doc.page_content[:90]}...")
                if score >= min_score:
                    filtered.append(doc)

            print(f"Documents after filtering (min_score={min_score}): {len(filtered)}")

            # Optional compression (can be slow with Ollama)
            if use_compression and filtered:
                try:
                    compressor = LLMChainExtractor.from_llm(self.llm)
                    compression_retriever = ContextualCompressionRetriever(
                        base_compressor=compressor,
                        base_retriever=self.vectorstore.as_retriever(search_kwargs={"k": k})
                    )
                    filtered = compression_retriever.invoke(query)
                    print(f"After compression: {len(filtered)} documents")
                except Exception as e:
                    print(f"Compression skipped due to error: {e}")

            # Add citations
            for i, doc in enumerate(filtered):
                doc.metadata["citation"] = f"{doc.metadata.get('source', 'Zepto')}#{i}"

            return filtered

        except Exception as e:
            print(f"RAG Error: {e}")
            return []