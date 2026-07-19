# Test
retriever = AdvancedRAGRetriever()
docs = retriever.retrieve(
    query="What is the return policy for damaged products in India?",
    metadata_filter={"category": "policy", "region": "IN"}
)

for doc in docs:
    print(doc.page_content[:300], "...")
    print("Citation:", doc.metadata.get("citation"))