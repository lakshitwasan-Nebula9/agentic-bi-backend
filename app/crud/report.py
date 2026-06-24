import uuid

from sqlalchemy.orm import Session

from app.models.report import Report


def create_report(db: Session, report: Report) -> Report:
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def get_report(db: Session, report_id: uuid.UUID) -> Report | None:
    return db.get(Report, report_id)


def list_reports(db: Session, limit: int = 50) -> list[Report]:
    return db.query(Report).order_by(Report.created_at.desc()).limit(limit).all()


def update_report(db: Session, report: Report, **kwargs) -> Report:
    for key, value in kwargs.items():
        setattr(report, key, value)
    db.commit()
    db.refresh(report)
    return report
