import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.crud import report as report_crud
from app.models.report import Report
from app.models.user import User, UserRole
from app.schemas.report import (
    ReportDetailResponse,
    ReportGenerateRequest,
    ReportResponse,
)

router = APIRouter(prefix="/reports", tags=["reports"])

logger = logging.getLogger(__name__)

GENERATE_ROLES = (UserRole.ANALYST, UserRole.MANAGER, UserRole.EXECUTIVE)


async def _run_generation(report_id: uuid.UUID, title: str, period_label: str) -> None:
    """Background task: generate and persist the full report."""
    from app.core.database import SessionLocal
    from app.services.report_generation_service import generate_report

    db = SessionLocal()
    try:
        await generate_report(db, report_id, title, period_label)
    except Exception:
        logger.exception("Background report generation failed for %s", report_id)
    finally:
        db.close()


@router.post("", response_model=ReportResponse, status_code=status.HTTP_202_ACCEPTED)
async def generate_report(
    payload: ReportGenerateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*GENERATE_ROLES)),
):
    """Trigger async report generation. Returns immediately with status=generating."""
    now = datetime.now(UTC)
    period_label = payload.period_label or now.strftime("%B %Y")
    title = payload.title or f"Executive Performance Report — {period_label}"

    report = Report(
        title=title,
        period_label=period_label,
        status="generating",
        generated_by=current_user.id,
    )
    report_crud.create_report(db, report)

    background_tasks.add_task(_run_generation, report.id, title, period_label)
    logger.info("Queued report generation %s for user %s", report.id, current_user.id)

    return report


@router.get("", response_model=list[ReportResponse])
def list_reports(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return report_crud.list_reports(db, limit=limit)


@router.get("/{report_id}", response_model=ReportDetailResponse)
def get_report(
    report_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    report = report_crud.get_report(db, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return report


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report(
    report_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*GENERATE_ROLES)),
):
    report = report_crud.get_report(db, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    db.delete(report)
    db.commit()
