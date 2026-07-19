def retrieve(self, query: str, metadata_filter: dict = None, min_score: float = 0.3):
    """Debug version of retrieve"""
    
    print(f"\n🔍 RAG Query: {query}")
    
    # Get documents with lower threshold for debugging
    docs = self.vectorstore.similarity_search_with_score(
        query,
        k=6,
        filter=metadata_filter
    )
    
    print(f"📊 Raw results from Pinecone: {len(docs)}")
    
    for i, (doc, score) in enumerate(docs):
        print(f"  [{i+1}] Score: {score:.4f} | Source: {doc.metadata.get('source')}")
        print(f"       Preview: {doc.page_content[:120]}...\n")
    
    # Filter by score
    filtered_docs = [doc for doc, score in docs if score >= min_score]
    
    print(f"✅ Documents after score filter ({min_score}): {len(filtered_docs)}")
    
    return filtered_docs