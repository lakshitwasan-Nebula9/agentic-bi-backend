import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.data_quality import QualityScorecardResponse
from app.services import data_quality_service
from app.services.dataset_service import get_dataset_or_404

router = APIRouter(prefix="/datasets", tags=["data-quality"])


@router.get("/{dataset_id}/quality", response_model=QualityScorecardResponse)
def get_quality_scorecard(
    dataset_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dataset = get_dataset_or_404(db, dataset_id)
    if dataset.quality_metrics is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quality scorecard not yet available. Run a sync or trigger quality check.",
        )
    return QualityScorecardResponse(
        **dataset.quality_metrics,
        overall_score=dataset.quality_score,
        should_quarantine=dataset.status == "quarantined",
    )


@router.post("/{dataset_id}/quality/run", response_model=QualityScorecardResponse)
def run_quality_check(
    dataset_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    get_dataset_or_404(db, dataset_id)
    try:
        scorecard = data_quality_service.run_quality_pipeline(db, dataset_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return QualityScorecardResponse(
        completeness=scorecard.completeness,
        consistency=scorecard.consistency,
        recency=scorecard.recency,
        overall_score=scorecard.overall_score,
        status_label=scorecard.status_label,
        should_quarantine=scorecard.should_quarantine,
        null_rate=scorecard.null_rate,
        type_issues=scorecard.type_issues,
        row_count=scorecard.row_count,
        column_count=scorecard.column_count,
        checked_at=scorecard.checked_at,
    )
