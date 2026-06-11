import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.dataset import Dataset, DatasetRecord


def get_dataset(db: Session, dataset_id: uuid.UUID) -> Dataset | None:
    return db.get(Dataset, dataset_id)


def get_dataset_by_name(db: Session, name: str) -> Dataset | None:
    return db.query(Dataset).filter(Dataset.name == name).first()


def list_datasets(db: Session) -> list[Dataset]:
    return db.query(Dataset).order_by(Dataset.name).all()


def create_dataset(db: Session, dataset: Dataset) -> Dataset:
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset


def delete_dataset(db: Session, dataset: Dataset) -> None:
    db.delete(dataset)
    db.commit()


def replace_dataset_records(db: Session, dataset_id: uuid.UUID, rows: list[dict]) -> None:
    db.query(DatasetRecord).filter(DatasetRecord.dataset_id == dataset_id).delete()
    for row in rows:
        db.add(DatasetRecord(dataset_id=dataset_id, row_data=row))
    db.commit()


def list_dataset_records(
    db: Session, dataset_id: uuid.UUID, limit: int = 100, offset: int = 0
) -> list[DatasetRecord]:
    return (
        db.query(DatasetRecord)
        .filter(DatasetRecord.dataset_id == dataset_id)
        .order_by(DatasetRecord.ingested_at)
        .offset(offset)
        .limit(limit)
        .all()
    )


def mark_synced(
    db: Session, dataset: Dataset, row_count: int, schema_fingerprint: dict, synced_at: datetime
) -> Dataset:
    dataset.row_count = row_count
    dataset.schema_fingerprint = schema_fingerprint
    dataset.last_synced_at = synced_at
    db.commit()
    db.refresh(dataset)
    return dataset
