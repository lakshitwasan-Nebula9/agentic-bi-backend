import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.dataset import Dataset, DatasetRecord


def get_dataset(
    db: Session, dataset_id: uuid.UUID, include_deleted: bool = False
) -> Dataset | None:
    q = db.query(Dataset).filter(Dataset.id == dataset_id)
    if not include_deleted:
        q = q.filter(Dataset.is_deleted.is_(False))
    return q.first()


def get_dataset_by_name(db: Session, name: str) -> Dataset | None:
    return db.query(Dataset).filter(Dataset.name == name, Dataset.is_deleted.is_(False)).first()


def list_datasets(db: Session, include_deleted: bool = False) -> list[Dataset]:
    q = db.query(Dataset)
    if not include_deleted:
        q = q.filter(Dataset.is_deleted.is_(False))
    return q.order_by(Dataset.name).all()


def create_dataset(db: Session, dataset: Dataset) -> Dataset:
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset


def delete_dataset(db: Session, dataset: Dataset) -> None:
    db.delete(dataset)
    db.commit()


def replace_dataset_records(db: Session, dataset_id: uuid.UUID, rows: list[dict]) -> None:
    # Only remove live records; soft-deleted records are left untouched.
    db.query(DatasetRecord).filter(
        DatasetRecord.dataset_id == dataset_id, DatasetRecord.is_deleted.is_(False)
    ).delete()
    for row in rows:
        db.add(DatasetRecord(dataset_id=dataset_id, row_data=row))
    db.commit()


def list_dataset_records(
    db: Session,
    dataset_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
    include_deleted: bool = False,
) -> list[DatasetRecord]:
    q = db.query(DatasetRecord).filter(DatasetRecord.dataset_id == dataset_id)
    if not include_deleted:
        q = q.filter(DatasetRecord.is_deleted.is_(False))
    return q.order_by(DatasetRecord.ingested_at).offset(offset).limit(limit).all()


def get_all_dataset_records(
    db: Session, dataset_id: uuid.UUID, include_deleted: bool = False
) -> list[DatasetRecord]:
    q = db.query(DatasetRecord).filter(DatasetRecord.dataset_id == dataset_id)
    if not include_deleted:
        q = q.filter(DatasetRecord.is_deleted.is_(False))
    return q.order_by(DatasetRecord.ingested_at).all()


def mark_synced(
    db: Session, dataset: Dataset, row_count: int, schema_fingerprint: dict, synced_at: datetime
) -> Dataset:
    dataset.row_count = row_count
    dataset.schema_fingerprint = schema_fingerprint
    dataset.last_synced_at = synced_at
    db.commit()
    db.refresh(dataset)
    return dataset


def update_quality_result(
    db: Session,
    dataset: Dataset,
    quality_metrics: dict,
    quality_score: float,
    status: str,
) -> Dataset:
    dataset.quality_metrics = quality_metrics
    dataset.quality_score = quality_score
    dataset.status = status
    db.commit()
    db.refresh(dataset)
    return dataset
