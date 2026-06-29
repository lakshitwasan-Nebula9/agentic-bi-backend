import uuid

from sqlalchemy.orm import Session

from app.models.connector import DataConnector


def get_connector(
    db: Session, connector_id: uuid.UUID, include_deleted: bool = False
) -> DataConnector | None:
    q = db.query(DataConnector).filter(DataConnector.id == connector_id)
    if not include_deleted:
        q = q.filter(DataConnector.is_deleted.is_(False))
    return q.first()


def get_connector_by_name(db: Session, name: str) -> DataConnector | None:
    return (
        db.query(DataConnector)
        .filter(DataConnector.name == name, DataConnector.is_deleted.is_(False))
        .first()
    )


def list_connectors(db: Session, include_deleted: bool = False) -> list[DataConnector]:
    q = db.query(DataConnector)
    if not include_deleted:
        q = q.filter(DataConnector.is_deleted.is_(False))
    return q.order_by(DataConnector.name).all()


def create_connector(db: Session, connector: DataConnector) -> DataConnector:
    db.add(connector)
    db.commit()
    db.refresh(connector)
    return connector


def update_connector(db: Session, connector: DataConnector, updates: dict) -> DataConnector:
    for field, value in updates.items():
        setattr(connector, field, value)
    db.commit()
    db.refresh(connector)
    return connector


def delete_connector(db: Session, connector: DataConnector) -> None:
    db.delete(connector)
    db.commit()
