import uuid

from pydantic import BaseModel


class ColumnInput(BaseModel):
    name: str
    type: str


class SchemaDetectRequest(BaseModel):
    table_name: str
    columns: list[ColumnInput]
    dataset_id: uuid.UUID | None = None


class ColumnAnnotation(BaseModel):
    name: str
    label: str
    business_definition: str
    role: str  # identifier | dimension | measure | date


class SchemaDetectResponse(BaseModel):
    table_name: str

    entity_type: str
    description: str

    columns: list[ColumnAnnotation]

    identifiers: list[str]
    dimensions: list[str]
    measures: list[str]
    date_columns: list[str]

    suggested_kpis: list[str]
    business_questions: list[str]

    embedding_id: uuid.UUID
    schema_metadata_id: uuid.UUID
