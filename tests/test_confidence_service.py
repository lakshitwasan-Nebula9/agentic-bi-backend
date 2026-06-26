"""Unit tests for confidence_service — pure scoring, no DB."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services.confidence_service import compute_confidence


def _insight(z_score=None, trend_slope=None):
    return SimpleNamespace(z_score=z_score, trend_slope=trend_slope)


def _dataset(quality_score=0.8, last_synced_at=None):
    if last_synced_at is None:
        last_synced_at = datetime.now(UTC)
    return SimpleNamespace(quality_score=quality_score, last_synced_at=last_synced_at)


def test_score_within_bounds():
    score, breakdown = compute_confidence(_insight(z_score=3.0), _dataset(), 12)
    assert 0 <= score <= 100
    assert set(breakdown) == {
        "statistical_strength",
        "data_quality",
        "freshness",
        "history_depth",
    }


def test_score_monotonic_in_z_score():
    """Stronger anomaly magnitude → higher (or equal) confidence, all else equal."""
    ds = _dataset()
    weak, _ = compute_confidence(_insight(z_score=1.0), ds, 12)
    strong, _ = compute_confidence(_insight(z_score=4.0), ds, 12)
    assert strong >= weak


def test_null_quality_falls_back_to_neutral():
    """A null quality_score must not crash and scores below a perfect-quality dataset."""
    null_q, _ = compute_confidence(_insight(z_score=3.0), _dataset(quality_score=None), 12)
    full_q, _ = compute_confidence(_insight(z_score=3.0), _dataset(quality_score=1.0), 12)
    assert 0 <= null_q <= 100
    assert full_q >= null_q


def test_freshness_decays_with_age():
    fresh = _dataset(last_synced_at=datetime.now(UTC))
    stale = _dataset(last_synced_at=datetime.now(UTC) - timedelta(days=30))
    fresh_score, _ = compute_confidence(_insight(z_score=3.0), fresh, 12)
    stale_score, _ = compute_confidence(_insight(z_score=3.0), stale, 12)
    assert fresh_score > stale_score


def test_stable_insight_still_scores_above_zero():
    """No anomaly, no trend → statistical floor + other signals keep score positive."""
    score, breakdown = compute_confidence(_insight(z_score=0.0, trend_slope=0.0), _dataset(), 12)
    assert score > 0
    assert breakdown["statistical_strength"]["value"] >= 0.3


def test_missing_dataset_does_not_crash():
    score, _ = compute_confidence(_insight(z_score=2.0), None, 0)
    assert 0 <= score <= 100
