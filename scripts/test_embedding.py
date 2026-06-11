"""Quick smoke test for the Gemini embedding API. Run with:
    python scripts/test_embedding.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from app.services.embedding_service import generate_embedding

print("Calling embed API...")
vec = generate_embedding("Customer churn rate")
print(f"Success! Got vector of length {len(vec)}")
print(f"First 5 values: {vec[:5]}")
