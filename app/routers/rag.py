from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.rag import EmbedRequest, EmbedResponse, SearchRequest, SearchResponse, SearchResult
from app.services.embedding_service import search_similar, upsert_embedding

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/embed", response_model=EmbedResponse, status_code=status.HTTP_201_CREATED)
def embed(payload: EmbedRequest, db: Session = Depends(get_db)):
    record = upsert_embedding(
        db,
        tenant_id=payload.tenant_id,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        content=payload.content,
    )
    return EmbedResponse(id=record.id, entity_type=record.entity_type, entity_id=record.entity_id)


@router.post("/search", response_model=SearchResponse)
def search(payload: SearchRequest, db: Session = Depends(get_db)):
    records = search_similar(
        db,
        tenant_id=payload.tenant_id,
        query=payload.query,
        entity_type=payload.entity_type,
        top_k=payload.top_k,
    )
    return SearchResponse(
        results=[
            SearchResult(
                id=r.id,
                entity_type=r.entity_type,
                entity_id=r.entity_id,
                content=r.content,
            )
            for r in records
        ]
    )
