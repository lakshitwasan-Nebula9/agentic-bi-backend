"""Deterministic confidence scoring for detected insights.

Produces a 0–100 score expressing how much an insight should be trusted, as a
weighted blend of normalised signals. Isolated here so a more sophisticated
Sprint-4 algorithm can replace the internals without touching the agent, the
receipt, or the API.
"""

from datetime import UTC, datetime

from app.models.dataset import Dataset
from app.models.insight import InsightEvent

# Component weights (must sum to 1.0).
W_STATISTICAL = 0.40
W_DATA_QUALITY = 0.30
W_FRESHNESS = 0.20
W_HISTORY = 0.10

# A z-score of 4 (or a trend of ~20%/month) is treated as maximally clear signal.
_Z_SATURATION = 4.0
_TREND_SATURATION = 20.0
# Baseline statistical confidence for a perfectly flat signal (z≈0, no trend).
# The actual signal is blended on top of this (see _statistical_strength), so even
# "stable" insights differentiate by their real deviation instead of all snapping
# to one value — rather than a hard floor that discards small z-scores.
_STAT_BASELINE = 0.30

# Freshness decay window: full marks under 1h old, zero by ~7 days.
_FRESH_FULL_HOURS = 1.0
_FRESH_ZERO_HOURS = 7 * 24
# A year of monthly snapshots earns full marks for history depth.
_HISTORY_FULL_POINTS = 12


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _statistical_strength(insight: InsightEvent) -> float:
    z_component = (
        _clamp01(abs(insight.z_score) / _Z_SATURATION) if insight.z_score is not None else 0.0
    )
    trend_component = (
        _clamp01(abs(insight.trend_slope) / _TREND_SATURATION)
        if insight.trend_slope is not None
        else 0.0
    )
    signal = max(z_component, trend_component)
    # Blend: a flat signal scores the baseline; stronger deviations scale up to 1.0,
    # so two "stable" insights with different z-scores get different scores.
    return _STAT_BASELINE + (1.0 - _STAT_BASELINE) * signal


def _data_quality(dataset: Dataset | None) -> float:
    if dataset is None or dataset.quality_score is None:
        return 0.5
    return _clamp01(dataset.quality_score)


def _freshness(dataset: Dataset | None) -> float:
    if dataset is None or dataset.last_synced_at is None:
        return 0.5
    synced = dataset.last_synced_at
    if synced.tzinfo is None:
        synced = synced.replace(tzinfo=UTC)
    age_hours = (datetime.now(UTC) - synced).total_seconds() / 3600.0
    if age_hours <= _FRESH_FULL_HOURS:
        return 1.0
    if age_hours >= _FRESH_ZERO_HOURS:
        return 0.0
    return 1.0 - (age_hours - _FRESH_FULL_HOURS) / (_FRESH_ZERO_HOURS - _FRESH_FULL_HOURS)


def _history_depth(num_snapshots: int) -> float:
    return _clamp01(num_snapshots / _HISTORY_FULL_POINTS)


def compute_confidence(
    insight: InsightEvent, dataset: Dataset | None, num_snapshots: int
) -> tuple[int, dict]:
    """Return (score 0–100, breakdown of normalised component scores)."""
    statistical = _statistical_strength(insight)
    quality = _data_quality(dataset)
    freshness = _freshness(dataset)
    history = _history_depth(num_snapshots)

    weighted = (
        W_STATISTICAL * statistical
        + W_DATA_QUALITY * quality
        + W_FRESHNESS * freshness
        + W_HISTORY * history
    )
    score = max(0, min(100, round(100 * weighted)))

    breakdown = {
        "statistical_strength": {"value": round(statistical, 3), "weight": W_STATISTICAL},
        "data_quality": {"value": round(quality, 3), "weight": W_DATA_QUALITY},
        "freshness": {"value": round(freshness, 3), "weight": W_FRESHNESS},
        "history_depth": {"value": round(history, 3), "weight": W_HISTORY},
    }
    return score, breakdown
