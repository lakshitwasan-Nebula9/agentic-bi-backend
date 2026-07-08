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
        .on_conflict_do_update(index_elements=[SchemaMetadata.table_name], set_=update_cols)
        .returning(SchemaMetadata.id)
    )

    record_id = db.execute(stmt).scalar_one()
    db.commit()
    return db.get(SchemaMetadata, record_id)


def get_schema_metadata_by_table(
    db: Session, table_name: str, include_deleted: bool = False
) -> SchemaMetadata | None:
    q = db.query(SchemaMetadata).filter(SchemaMetadata.table_name == table_name)
    if not include_deleted:
        q = q.filter(SchemaMetadata.is_deleted.is_(False))
    return q.first()
