import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.insight import InsightEventResponse
from app.services import insight_service

router = APIRouter(tags=["insights"])


@router.post("/insights/detect", response_model=list[InsightEventResponse], status_code=201)
async def detect_insights(db: Session = Depends(get_db)):
    """Run anomaly detection across all certified KPIs and persist new InsightEvents.

    Each new event is narrated by Gemini in the same pass (best-effort).
    Idempotent — skips KPIs whose latest period has already been analysed.
    """
    return await insight_service.detect_all(db)


@router.get("/insights", response_model=list[InsightEventResponse])
def list_insights(
    kpi_id: uuid.UUID | None = None,
    insight_type: str | None = None,
    is_anomaly: bool | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return insight_service.list_insights(
        db, kpi_id=kpi_id, insight_type=insight_type, is_anomaly=is_anomaly, limit=limit
    )


@router.get("/insights/kpi/{kpi_id}", response_model=list[InsightEventResponse])
def list_insights_for_kpi(kpi_id: uuid.UUID, limit: int = 50, db: Session = Depends(get_db)):
    return insight_service.list_insights(db, kpi_id=kpi_id, limit=limit)


@router.post("/insights/kpi/{kpi_id}/detect", response_model=InsightEventResponse | None)
async def detect_for_kpi(kpi_id: uuid.UUID, db: Session = Depends(get_db)):
    """Run detection for a single KPI. Returns null when conditions aren't met."""
    return await insight_service.detect_for_kpi(db, kpi_id)
