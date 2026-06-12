import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.crud import dataset as dataset_crud
from app.crud.dataset import get_all_dataset_records

# ---------------------------------------------------------------------------
# Layer 1: Data Profiling
# ---------------------------------------------------------------------------


@dataclass
class ColumnProfile:
    null_count: int
    non_null_count: int
    null_rate: float
    type_distribution: dict[str, int]
    dominant_type: str
    dominant_type_count: int


@dataclass
class DataProfile:
    row_count: int
    column_count: int
    columns: dict[str, ColumnProfile] = field(default_factory=dict)


def profile_dataset(records: list[dict[str, Any]]) -> DataProfile:
    if not records:
        return DataProfile(row_count=0, column_count=0)

    all_columns: set[str] = set()
    for row in records:
        all_columns.update(row.keys())

    columns: dict[str, ColumnProfile] = {}
    for col in all_columns:
        type_dist: dict[str, int] = {}
        null_count = 0

        for row in records:
            value = row.get(col)
            if value is None:
                null_count += 1
                type_dist["NoneType"] = type_dist.get("NoneType", 0) + 1
            else:
                type_name = type(value).__name__
                type_dist[type_name] = type_dist.get(type_name, 0) + 1

        non_null_count = len(records) - null_count
        non_none_types = {k: v for k, v in type_dist.items() if k != "NoneType"}
        dominant_type = (
            max(non_none_types, key=non_none_types.get) if non_none_types else "NoneType"
        )
        dominant_type_count = non_none_types.get(dominant_type, 0)

        columns[col] = ColumnProfile(
            null_count=null_count,
            non_null_count=non_null_count,
            null_rate=null_count / len(records),
            type_distribution=type_dist,
            dominant_type=dominant_type,
            dominant_type_count=dominant_type_count,
        )

    return DataProfile(
        row_count=len(records),
        column_count=len(columns),
        columns=columns,
    )


# ---------------------------------------------------------------------------
# Layer 2: Quality Validation
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    completeness_score: float
    consistency_score: float
    recency_score: float
    null_rates: dict[str, float]
    type_issues: list[str]
    hours_since_sync: float | None


def _recency_score(hours: float | None) -> float:
    if hours is None:
        return 0.0
    if hours < 1:
        return 1.0
    if hours < 24:
        return 1.0 - (0.3 * (hours - 1) / 23)
    if hours < 72:
        return 0.7 - (0.4 * (hours - 24) / 48)
    if hours < 168:
        return max(0.0, 0.3 - (0.3 * (hours - 72) / 96))
    return 0.0


def validate_profile(profile: DataProfile, synced_at: datetime | None) -> ValidationResult:
    if profile.row_count == 0 or not profile.columns:
        hours = None
        if synced_at is not None:
            hours = (datetime.now(UTC) - synced_at).total_seconds() / 3600
        return ValidationResult(
            completeness_score=0.0,
            consistency_score=0.0,
            recency_score=_recency_score(hours),
            null_rates={},
            type_issues=["No data rows found"],
            hours_since_sync=hours,
        )

    completeness_per_col = [
        col.non_null_count / profile.row_count for col in profile.columns.values()
    ]
    completeness_score = sum(completeness_per_col) / len(completeness_per_col)

    consistency_per_col: list[float] = []
    type_issues: list[str] = []

    for col_name, col in profile.columns.items():
        if col.non_null_count == 0:
            consistency_per_col.append(1.0)
            continue
        col_consistency = col.dominant_type_count / col.non_null_count
        consistency_per_col.append(col_consistency)
        if col_consistency < 0.95:
            type_issues.append(
                f"{col_name}: mixed types ({col.dominant_type} is "
                f"{col_consistency:.0%} of non-null values)"
            )

    consistency_score = sum(consistency_per_col) / len(consistency_per_col)

    hours_since_sync: float | None = None
    if synced_at is not None:
        hours_since_sync = (datetime.now(UTC) - synced_at).total_seconds() / 3600

    return ValidationResult(
        completeness_score=completeness_score,
        consistency_score=consistency_score,
        recency_score=_recency_score(hours_since_sync),
        null_rates={col: profile.columns[col].null_rate for col in profile.columns},
        type_issues=type_issues,
        hours_since_sync=hours_since_sync,
    )


# ---------------------------------------------------------------------------
# Layer 3: Quality Scoring
# ---------------------------------------------------------------------------

_WEIGHTS = {"completeness": 0.40, "consistency": 0.30, "recency": 0.30}


@dataclass
class QualityScorecard:
    completeness: float
    consistency: float
    recency: float
    overall_score: float
    status_label: str
    should_quarantine: bool
    null_rate: dict[str, float]
    type_issues: list[str]
    row_count: int
    column_count: int
    checked_at: str


def score_validation(result: ValidationResult, profile: DataProfile) -> QualityScorecard:
    overall = (
        result.completeness_score * _WEIGHTS["completeness"]
        + result.consistency_score * _WEIGHTS["consistency"]
        + result.recency_score * _WEIGHTS["recency"]
    ) * 100

    if overall >= 80:
        label = "healthy"
    elif overall >= settings.DATA_QUALITY_THRESHOLD:
        label = "warning"
    else:
        label = "critical"

    return QualityScorecard(
        completeness=round(result.completeness_score, 4),
        consistency=round(result.consistency_score, 4),
        recency=round(result.recency_score, 4),
        overall_score=round(overall, 2),
        status_label=label,
        should_quarantine=overall < settings.DATA_QUALITY_THRESHOLD,
        null_rate={col: round(rate, 4) for col, rate in result.null_rates.items()},
        type_issues=result.type_issues,
        row_count=profile.row_count,
        column_count=profile.column_count,
        checked_at=datetime.now(UTC).isoformat(),
    )


# ---------------------------------------------------------------------------
# Layer 4: Quarantine & Routing
# ---------------------------------------------------------------------------


def apply_quality_result(db: Session, dataset_id: uuid.UUID, scorecard: QualityScorecard) -> None:
    dataset = dataset_crud.get_dataset(db, dataset_id)
    if dataset is None:
        return

    new_status = "quarantined" if scorecard.should_quarantine else "active"
    quality_metrics = {
        "completeness": scorecard.completeness,
        "consistency": scorecard.consistency,
        "recency": scorecard.recency,
        "null_rate": scorecard.null_rate,
        "type_issues": scorecard.type_issues,
        "row_count": scorecard.row_count,
        "column_count": scorecard.column_count,
        "status_label": scorecard.status_label,
        "checked_at": scorecard.checked_at,
    }

    dataset_crud.update_quality_result(
        db,
        dataset,
        quality_metrics=quality_metrics,
        quality_score=scorecard.overall_score,
        status=new_status,
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_quality_pipeline(db: Session, dataset_id: uuid.UUID) -> QualityScorecard:
    dataset = dataset_crud.get_dataset(db, dataset_id)
    if dataset is None:
        raise ValueError(f"Dataset {dataset_id} not found")

    records_orm = get_all_dataset_records(db, dataset_id)
    rows = [r.row_data for r in records_orm]

    profile = profile_dataset(rows)
    validation = validate_profile(profile, dataset.last_synced_at)
    scorecard = score_validation(validation, profile)
    apply_quality_result(db, dataset_id, scorecard)

    return scorecard
