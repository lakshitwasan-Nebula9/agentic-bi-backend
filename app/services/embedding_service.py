import uuid
from functools import lru_cache
from typing import Literal

from sentence_transformers import SentenceTransformer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.embeddings import EmbeddingRecord


@lru_cache(maxsize=1)
def _load_model() -> SentenceTransformer:
    return SentenceTransformer(settings.EMBEDDING_MODEL, trust_remote_code=True)


def generate_embedding(text: str, mode: Literal["document", "query"] = "document") -> list[float]:
    """Generate an embedding vector for the given text.

    nomic-embed-text-v1 requires task-type prefixes for best quality.
    """
    prefix = "search_document: " if mode == "document" else "search_query: "
    model = _load_model()
    return model.encode(prefix + text).tolist()


def upsert_embedding(
    db: Session,
    tenant_id: uuid.UUID,
    entity_type: str,
    entity_id: str,
    content: str,
) -> EmbeddingRecord:
    """Store or update an embedding record for a given entity."""
    embedding = generate_embedding(content, mode="document")

    record = (
        db.query(EmbeddingRecord)
        .filter(
            EmbeddingRecord.tenant_id == tenant_id,
            EmbeddingRecord.entity_type == entity_type,
            EmbeddingRecord.entity_id == entity_id,
        )
        .first()
    )

    if record:
        record.content = content
        record.embedding = embedding
    else:
        record = EmbeddingRecord(
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            content=content,
            embedding=embedding,
        )
        db.add(record)

    db.commit()
    db.refresh(record)
    return record


def search_similar(
    db: Session,
    tenant_id: uuid.UUID,
    query: str,
    entity_type: str | None = None,
    top_k: int = 5,
) -> list[EmbeddingRecord]:
    """Return top-k records closest to the query vector (cosine distance)."""
    query_embedding = generate_embedding(query, mode="query")

    q = db.query(EmbeddingRecord).filter(EmbeddingRecord.tenant_id == tenant_id)
    if entity_type:
        q = q.filter(EmbeddingRecord.entity_type == entity_type)

    return (
        q.order_by(EmbeddingRecord.embedding.cosine_distance(query_embedding))
        .limit(top_k)
        .all()
    )
