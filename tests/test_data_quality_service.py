import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.services.data_quality_service import (
    DataProfile,
    QualityScorecard,
    ValidationResult,
    _recency_score,
    apply_quality_result,
    profile_dataset,
    run_quality_pipeline,
    score_validation,
    validate_profile,
)

# ---------------------------------------------------------------------------
# Layer 1: profile_dataset
# ---------------------------------------------------------------------------


def test_profile_empty_dataset():
    result = profile_dataset([])
    assert result.row_count == 0
    assert result.column_count == 0
    assert result.columns == {}


def test_profile_all_non_null():
    rows = [{"amount": 100, "name": "alice"}, {"amount": 200, "name": "bob"}]
    profile = profile_dataset(rows)
    assert profile.row_count == 2
    assert profile.column_count == 2
    assert profile.columns["amount"].null_count == 0
    assert profile.columns["amount"].non_null_count == 2
    assert profile.columns["amount"].null_rate == 0.0
    assert profile.columns["amount"].dominant_type == "int"


def test_profile_with_nulls():
    rows = [{"x": 1}, {"x": None}, {"x": 3}, {"x": None}]
    profile = profile_dataset(rows)
    assert profile.columns["x"].null_count == 2
    assert profile.columns["x"].null_rate == 0.5


def test_profile_mixed_types():
    rows = [{"v": 1}, {"v": "two"}, {"v": 3}, {"v": 4}, {"v": 5}]
    profile = profile_dataset(rows)
    col = profile.columns["v"]
    assert col.dominant_type == "int"
    assert col.dominant_type_count == 4
    assert "str" in col.type_distribution


# ---------------------------------------------------------------------------
# Layer 2: validate_profile — recency helper
# ---------------------------------------------------------------------------


def test_recency_score_fresh():
    assert _recency_score(0.5) == 1.0


def test_recency_score_one_day():
    score = _recency_score(24)
    assert 0.65 < score < 0.75


def test_recency_score_old():
    assert _recency_score(200) == 0.0


def test_recency_score_none():
    assert _recency_score(None) == 0.0


def test_validate_empty_profile():
    profile = DataProfile(row_count=0, column_count=0)
    result = validate_profile(profile, synced_at=None)
    assert result.completeness_score == 0.0
    assert result.consistency_score == 0.0
    assert result.recency_score == 0.0


def test_validate_perfect_data():
    rows = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
    profile = profile_dataset(rows)
    synced_at = datetime.now(UTC) - timedelta(minutes=10)
    result = validate_profile(profile, synced_at)
    assert result.completeness_score == 1.0
    assert result.consistency_score == 1.0
    assert result.recency_score > 0.95


def test_validate_detects_type_issue():
    rows = [{"v": 1}, {"v": "x"}, {"v": 2}, {"v": 3}, {"v": 4}]
    profile = profile_dataset(rows)
    result = validate_profile(profile, synced_at=datetime.now(UTC))
    assert len(result.type_issues) == 1
    assert "v" in result.type_issues[0]


# ---------------------------------------------------------------------------
# Layer 3: score_validation
# ---------------------------------------------------------------------------


def test_score_healthy():
    profile = DataProfile(row_count=100, column_count=3)
    result = ValidationResult(
        completeness_score=1.0,
        consistency_score=1.0,
        recency_score=1.0,
        null_rates={"a": 0.0},
        type_issues=[],
        hours_since_sync=0.5,
    )
    scorecard = score_validation(result, profile)
    assert scorecard.overall_score == 100.0
    assert scorecard.status_label == "healthy"
    assert scorecard.should_quarantine is False


def test_score_critical_triggers_quarantine():
    profile = DataProfile(row_count=100, column_count=2)
    result = ValidationResult(
        completeness_score=0.2,
        consistency_score=0.3,
        recency_score=0.0,
        null_rates={"a": 0.8},
        type_issues=["a: mixed types"],
        hours_since_sync=None,
    )
    scorecard = score_validation(result, profile)
    assert scorecard.overall_score < 60
    assert scorecard.status_label == "critical"
    assert scorecard.should_quarantine is True


def test_score_warning_band():
    profile = DataProfile(row_count=50, column_count=1)
    result = ValidationResult(
        completeness_score=0.85,
        consistency_score=0.75,
        recency_score=0.50,
        null_rates={},
        type_issues=[],
        hours_since_sync=30,
    )
    scorecard = score_validation(result, profile)
    assert 60 <= scorecard.overall_score < 80
    assert scorecard.status_label == "warning"
    assert scorecard.should_quarantine is False


# ---------------------------------------------------------------------------
# Layer 4: apply_quality_result
# ---------------------------------------------------------------------------


def test_apply_quality_result_quarantine():
    db = MagicMock()
    dataset = MagicMock()
    scorecard = QualityScorecard(
        completeness=0.2,
        consistency=0.3,
        recency=0.0,
        overall_score=17.0,
        status_label="critical",
        should_quarantine=True,
        null_rate={"x": 0.8},
        type_issues=[],
        row_count=10,
        column_count=1,
        checked_at="2026-06-12T00:00:00+00:00",
    )

    with patch("app.services.data_quality_service.dataset_crud.get_dataset", return_value=dataset):
        with patch(
            "app.services.data_quality_service.dataset_crud.update_quality_result"
        ) as mock_update:
            apply_quality_result(db, uuid.uuid4(), scorecard)
            mock_update.assert_called_once()
            _, kwargs = mock_update.call_args
            assert kwargs["status"] == "quarantined"


def test_apply_quality_result_active():
    db = MagicMock()
    dataset = MagicMock()
    scorecard = QualityScorecard(
        completeness=1.0,
        consistency=1.0,
        recency=1.0,
        overall_score=100.0,
        status_label="healthy",
        should_quarantine=False,
        null_rate={},
        type_issues=[],
        row_count=100,
        column_count=5,
        checked_at="2026-06-12T00:00:00+00:00",
    )

    with patch("app.services.data_quality_service.dataset_crud.get_dataset", return_value=dataset):
        with patch(
            "app.services.data_quality_service.dataset_crud.update_quality_result"
        ) as mock_update:
            apply_quality_result(db, uuid.uuid4(), scorecard)
            _, kwargs = mock_update.call_args
            assert kwargs["status"] == "active"


# ---------------------------------------------------------------------------
# Orchestrator: run_quality_pipeline
# ---------------------------------------------------------------------------


def test_run_quality_pipeline_raises_for_missing_dataset():
    db = MagicMock()
    with patch("app.services.data_quality_service.dataset_crud.get_dataset", return_value=None):
        with pytest.raises(ValueError, match="not found"):
            run_quality_pipeline(db, uuid.uuid4())


def test_run_quality_pipeline_end_to_end():
    db = MagicMock()
    dataset = MagicMock()
    dataset.last_synced_at = datetime.now(UTC) - timedelta(minutes=5)

    fake_records = [MagicMock(row_data={"amount": i, "name": f"user_{i}"}) for i in range(20)]

    with patch("app.services.data_quality_service.dataset_crud.get_dataset", return_value=dataset):
        with patch(
            "app.services.data_quality_service.get_all_dataset_records", return_value=fake_records
        ):
            with patch("app.services.data_quality_service.dataset_crud.update_quality_result"):
                scorecard = run_quality_pipeline(db, uuid.uuid4())

    assert scorecard.row_count == 20
    assert scorecard.overall_score > 60
    assert scorecard.status_label in ("healthy", "warning", "critical")
