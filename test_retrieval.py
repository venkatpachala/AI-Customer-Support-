# rag/clear_index.py
from pinecone import Pinecone
import os
from dotenv import load_dotenv

load_dotenv()

pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index = pc.Index(os.getenv("PINECONE_INDEX_NAME"))

# Delete all vectors
index.delete(delete_all=True)
print("✅ All previous documents deleted from Pinecone index.")