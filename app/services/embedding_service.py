import uuid
from functools import lru_cache

from sentence_transformers import SentenceTransformer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.embeddings import EmbeddingRecord


@lru_cache(maxsize=1)
def _load_model() -> SentenceTransformer:
    return SentenceTransformer(settings.EMBEDDING_MODEL)


def generate_embedding(text: str) -> list[float]:
    return _load_model().encode(text).tolist()


def upsert_embedding(
    db: Session,
    tenant_id: uuid.UUID,
    entity_type: str,
    entity_id: str,
    content: str,
) -> EmbeddingRecord:
    embedding = generate_embedding(content)

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
    query_embedding = generate_embedding(query)

    q = db.query(EmbeddingRecord).filter(EmbeddingRecord.tenant_id == tenant_id)
    if entity_type:
        q = q.filter(EmbeddingRecord.entity_type == entity_type)

    return (
        q.order_by(EmbeddingRecord.embedding.cosine_distance(query_embedding))
        .limit(top_k)
        .all()
    )
