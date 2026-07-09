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

GENERATE_ROLES = (UserRole.MANAGER, UserRole.EXECUTIVE)


async def _run_generation(
    report_id: uuid.UUID,
    title: str,
    period_label: str,
    scope: str,
    dashboard_id: uuid.UUID | None,
    connector_id: uuid.UUID | None,
) -> None:
    """Background task: generate and persist the full report."""
    from app.core.database import SessionLocal
    from app.services.report_generation_service import generate_report

    db = SessionLocal()
    try:
        await generate_report(
            db,
            report_id,
            title,
            period_label,
            scope=scope,
            dashboard_id=dashboard_id,
            connector_id=connector_id,
        )
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
    """Trigger async report generation. Returns immediately with status=generating.

    Scope is derived from the payload: a dashboard_id produces a dashboard-scoped
    report (that dashboard's KPIs only), a connector_id produces a database-scoped
    report (all certified KPIs of that connector), and neither yields a global report.
    """
    now = datetime.now(UTC)
    period_label = payload.period_label or now.strftime("%B %Y")

    # Resolve scope + a sensible default title from the scoped entity's name.
    if payload.dashboard_id is not None:
        from app.crud import dashboard as dashboard_crud

        dashboard = dashboard_crud.get_dashboard(db, payload.dashboard_id)
        if dashboard is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dashboard not found")
        scope = "dashboard"
        default_title = f"{dashboard.name} — Dashboard Report ({period_label})"
    elif payload.connector_id is not None:
        from app.crud.connector import get_connector

        connector = get_connector(db, payload.connector_id)
        if connector is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Database not found")
        scope = "database"
        default_title = f"{connector.name} — Database Report ({period_label})"
    else:
        scope = "global"
        default_title = f"Executive Performance Report — {period_label}"

    title = payload.title or default_title

    report = Report(
        title=title,
        period_label=period_label,
        status="generating",
        scope=scope,
        dashboard_id=payload.dashboard_id,
        connector_id=payload.connector_id,
        generated_by=current_user.id,
    )
    report_crud.create_report(db, report)

    background_tasks.add_task(
        _run_generation,
        report.id,
        title,
        period_label,
        scope,
        payload.dashboard_id,
        payload.connector_id,
    )
    logger.info("Queued %s report generation %s for user %s", scope, report.id, current_user.id)

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


@router.post("/trigger/weekly", status_code=status.HTTP_202_ACCEPTED)
async def trigger_weekly_report(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_role(*GENERATE_ROLES)),
):
    """Manually trigger the weekly report job (sends emails to Managers + Analysts)."""
    from app.services.report_scheduler import _run_weekly_job

    background_tasks.add_task(_run_weekly_job)
    return {"message": "Weekly report job queued"}


@router.post("/trigger/monthly", status_code=status.HTTP_202_ACCEPTED)
async def trigger_monthly_report(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_role(*GENERATE_ROLES)),
):
    """Manually trigger the monthly report job (sends emails to Executives + Managers)."""
    from app.services.report_scheduler import _run_monthly_job

    background_tasks.add_task(_run_monthly_job)
    return {"message": "Monthly report job queued"}


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
