import os
from typing import List, Dict, Optional
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_pinecone import PineconeVectorStore
from langchain_classic.retrievers import ContextualCompressionRetriever
from langchain_classic.retrievers.document_compressors import LLMChainExtractor
from langchain_core.documents import Document
from pinecone import Pinecone
from dotenv import load_dotenv

load_dotenv()

class AdvancedRAGRetriever:
    def __init__(self, index_name: str = os.getenv("PINECONE_INDEX_NAME")):
        self.pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
        self.vectorstore = PineconeVectorStore(
            index_name=index_name,
            embedding=self.embeddings
        )
        self.llm = ChatOpenAI(model="qwen2.5:7b", temperature=0)
        
        # Compressor for context compression
        compressor = LLMChainExtractor.from_llm(self.llm)
        self.compression_retriever = ContextualCompressionRetriever(
            base_compressor=compressor,
            base_retriever=self.vectorstore.as_retriever(
                search_kwargs={"k": 8}  # Fetch more, then compress
            )
        )

    def retrieve(self, query: str, 
                 metadata_filter: Optional[Dict] = None,
                 min_score: float = 0.75) -> List[Document]:
        """Production-grade retrieval"""
        
        # Base retriever
        base_retriever = self.vectorstore.as_retriever(
            search_kwargs={
                "k": 8,
                "filter": metadata_filter,
                "score_threshold": min_score
            }
        )
        
        # Compression
        compressor = LLMChainExtractor.from_llm(self.llm)
        compression_retriever = ContextualCompressionRetriever(
            base_compressor=compressor,
            base_retriever=base_retriever
        )
        
        # Use .invoke() instead of old method
        docs = compression_retriever.invoke(query)
        
        # Add citations
        for doc in docs:
            doc.metadata["citation"] = f"{doc.metadata.get('source', 'doc')} - {doc.metadata.get('chunk_id', '')}"
        
        return docs

    def add_documents(self, docs: List[Document], namespace: str = "default"):
        """Ingestion helper"""
        self.vectorstore.add_documents(docs, namespace=namespace)