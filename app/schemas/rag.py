import uuid

from pydantic import BaseModel, Field


class EmbedRequest(BaseModel):
    tenant_id: uuid.UUID
    entity_type: str = Field(..., examples=["kpi_definition", "business_term", "schema_description"])
    entity_id: str
    content: str


class EmbedResponse(BaseModel):
    id: uuid.UUID
    entity_type: str
    entity_id: str


class SearchRequest(BaseModel):
    tenant_id: uuid.UUID
    query: str
    entity_type: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class SearchResult(BaseModel):
    id: uuid.UUID
    entity_type: str
    entity_id: str
    content: str


class SearchResponse(BaseModel):
    results: list[SearchResult]
