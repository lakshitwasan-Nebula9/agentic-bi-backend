import uuid

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.schema_metadata import SchemaMetadata


def upsert_schema_metadata(
    db: Session,
    table_name: str,
    entity_type: str,
    description: str,
    columns: list,
    identifiers: list[str],
    dimensions: list[str],
    measures: list[str],
    date_columns: list[str],
    suggested_kpis: list[str],
    business_questions: list[str],
    dataset_id: uuid.UUID | None = None,
) -> SchemaMetadata:
    values = {
        "table_name": table_name,
        "entity_type": entity_type,
        "description": description,
        "columns": [c.model_dump() if hasattr(c, "model_dump") else c for c in columns],
        "identifiers": identifiers,
        "dimensions": dimensions,
        "measures": measures,
        "date_columns": date_columns,
        "suggested_kpis": suggested_kpis,
        "business_questions": business_questions,
        "is_deleted": False,
        "deleted_at": None,
    }

    update_cols = dict(values)
    if dataset_id is not None:
        update_cols["dataset_id"] = dataset_id

    stmt = (
        insert(SchemaMetadata)
        .values(id=uuid.uuid4(), dataset_id=dataset_id, **values)
        .on_conflict_do_update(
            index_elements=[SchemaMetadata.dataset_id, SchemaMetadata.table_name],
            set_=update_cols,
        )
        .returning(SchemaMetadata.id)
    )

    record_id = db.execute(stmt).scalar_one()
    db.commit()
    return db.get(SchemaMetadata, record_id)


def get_schema_metadata_by_table(
    db: Session,
    table_name: str,
    dataset_id: uuid.UUID | None = None,
    include_deleted: bool = False,
) -> SchemaMetadata | None:
    """Look up schema metadata for a table, scoped to a dataset when given.

    Two datasets can share a table name (e.g. two connectors pointed at the same source
    DB), so an unscoped lookup is ambiguous. When ``dataset_id`` is provided, only a row
    scoped to that exact dataset is returned — no fallback to unscoped/other-dataset rows,
    since those may belong to a different source and would silently feed wrong schema data
    into KPI generation. Callers should auto-detect (see kpi_agent._ensure_schema_metadata)
    when this returns None for a known dataset.
    """
    q = db.query(SchemaMetadata).filter(SchemaMetadata.table_name == table_name)
    if not include_deleted:
        q = q.filter(SchemaMetadata.is_deleted.is_(False))
    if dataset_id is None:
        return q.filter(SchemaMetadata.dataset_id.is_(None)).first()
    return q.filter(SchemaMetadata.dataset_id == dataset_id).first()
