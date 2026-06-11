"""Quick smoke test for the embedding service. Run with:
    python scripts/test_embedding.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# load_dotenv must run before app imports so settings picks up .env values
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.services.embedding_service import generate_embedding  # noqa: E402

print("Calling embed API...")
vec = generate_embedding("Customer churn rate")
print(f"Success! Got vector of length {len(vec)}")
print(f"First 5 values: {vec[:5]}")
