import uuid

from sqlalchemy.orm import Session

from app.models.connector import DataConnector


def get_connector(db: Session, connector_id: uuid.UUID) -> DataConnector | None:
    return db.get(DataConnector, connector_id)


def get_connector_by_name(db: Session, name: str) -> DataConnector | None:
    return db.query(DataConnector).filter(DataConnector.name == name).first()


def list_connectors(db: Session) -> list[DataConnector]:
    return db.query(DataConnector).order_by(DataConnector.name).all()


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
