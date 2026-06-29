import uuid

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
    record = (
        db.query(SchemaMetadata)
        .filter(SchemaMetadata.table_name == table_name, SchemaMetadata.is_deleted.is_(False))
        .first()
    )

    if record:
        record.entity_type = entity_type
        record.description = description
        record.columns = [c.model_dump() if hasattr(c, "model_dump") else c for c in columns]
        record.identifiers = identifiers
        record.dimensions = dimensions
        record.measures = measures
        record.date_columns = date_columns
        record.suggested_kpis = suggested_kpis
        record.business_questions = business_questions
        if dataset_id is not None:
            record.dataset_id = dataset_id
    else:
        record = SchemaMetadata(
            dataset_id=dataset_id,
            table_name=table_name,
            entity_type=entity_type,
            description=description,
            columns=[c.model_dump() if hasattr(c, "model_dump") else c for c in columns],
            identifiers=identifiers,
            dimensions=dimensions,
            measures=measures,
            date_columns=date_columns,
            suggested_kpis=suggested_kpis,
            business_questions=business_questions,
        )
        db.add(record)

    db.commit()
    db.refresh(record)
    return record


def get_schema_metadata_by_table(
    db: Session, table_name: str, include_deleted: bool = False
) -> SchemaMetadata | None:
    q = db.query(SchemaMetadata).filter(SchemaMetadata.table_name == table_name)
    if not include_deleted:
        q = q.filter(SchemaMetadata.is_deleted.is_(False))
    return q.first()
