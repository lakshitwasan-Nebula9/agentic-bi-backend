"""
Pure math functions for the Insight Agent math layer.

No DB access, no side effects — all functions take plain floats and return floats.
Input values must be in chronological order (oldest first).

Anomaly detection is *detrended*: we fit a linear trend on the prior periods,
predict the value for the current period, and z-score how far the actual value
deviates from that prediction (scaled by the historical residual spread). This
separates a genuine one-off spike/dip from an expected trend — a steadily
growing KPI is reported as ``trend_up``, not flagged as an anomaly.

Thresholds:
  - Anomaly:    |z_score| > Z_THRESHOLD (2.0)  — deviation from the trend line
  - Trend up:   trend_slope_pct > SLOPE_THRESHOLD (5 % / month)
  - Trend down: trend_slope_pct < -SLOPE_THRESHOLD
  - Stable:     everything else
"""

import math
from dataclasses import dataclass

Z_THRESHOLD = 2.0
SLOPE_THRESHOLD = 5.0  # % per month
MIN_SNAPSHOTS = 3  # minimum history for rolling averages / trend slope
# Detrended z-score needs >= 3 history points (so the fitted line has residual
# spread to measure against), i.e. >= 4 total values.
MIN_ZSCORE_HISTORY = 3


@dataclass
class MathResult:
    z_score: float | None
    baseline_mean: float | None  # trend-predicted ("expected") value for the period
    baseline_std: float | None  # std of historical residuals around the trend line
    rolling_avg_3m: float | None
    rolling_avg_6m: float | None
    trend_slope: float | None  # normalised % change per month
    insight_type: str
    is_anomaly: bool


def _ols(values: list[float]) -> tuple[float, float] | None:
    """Ordinary least squares fit over indices 0..n-1. Returns (slope, intercept).

    Returns None when fewer than 2 points exist or the x-variance is zero.
    """
    n = len(values)
    if n < 2:
        return None

    x = list(range(n))
    sum_x = sum(x)
    sum_y = sum(values)
    sum_xy = sum(xi * yi for xi, yi in zip(x, values, strict=False))
    sum_x2 = sum(xi**2 for xi in x)

    denom = n * sum_x2 - sum_x**2
    if denom == 0:
        return None

    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    return slope, intercept


def compute_z_score(values: list[float]) -> tuple[float, float, float] | tuple[None, None, None]:
    """Detrended z-score of the latest value against the trend through prior periods.

    Fits a line on ``values[:-1]``, predicts the latest period, and scales the
    residual by the std of the historical residuals.

    Returns ``(z_score, expected, residual_std)`` where ``expected`` is the
    trend-predicted value for the latest period. Returns ``(None, ...)`` when
    there is too little history or the residual spread is zero (e.g. a perfectly
    linear series — no deviation to report).
    """
    if len(values) < MIN_SNAPSHOTS:
        return None, None, None

    history = values[:-1]
    current = values[-1]

    if len(history) < MIN_ZSCORE_HISTORY:
        return None, None, None

    fit = _ols(history)
    if fit is None:
        return None, None, None
    slope, intercept = fit

    # Residuals of the history points around their own fitted line.
    residuals = [history[i] - (intercept + slope * i) for i in range(len(history))]
    # Regression residual variance uses (n - 2) degrees of freedom.
    dof = len(residuals) - 2
    if dof < 1:
        return None, None, None
    ssr = sum(r**2 for r in residuals)
    residual_std = math.sqrt(ssr / dof)

    # Expected value for the latest period (next index after the history).
    expected = intercept + slope * len(history)

    if residual_std == 0:
        return None, expected, residual_std

    return (current - expected) / residual_std, expected, residual_std


def compute_rolling_average(values: list[float], window: int) -> float | None:
    """Average of the last `window` values (including current). None if fewer values exist."""
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def compute_trend_slope(values: list[float]) -> float | None:
    """Normalised linear-regression slope as % change per period.

    Uses ordinary least squares over all values. Returns None when fewer than
    MIN_SNAPSHOTS values exist or the mean is zero (division undefined).
    """
    if len(values) < MIN_SNAPSHOTS:
        return None

    fit = _ols(values)
    if fit is None:
        return None
    slope, _ = fit

    mean = sum(values) / len(values)
    if mean == 0:
        return None

    return (slope / mean) * 100  # % change per month


def classify(
    z_score: float | None,
    trend_slope: float | None,
) -> tuple[str, bool]:
    """Return (insight_type, is_anomaly) from pre-computed z_score and trend_slope.

    ``z_score`` is the *detrended* deviation, so a strong trend on its own does
    not trip the anomaly check — only a value that departs from its own trend line
    does. A KPI moving along a steep but steady trend is reported as trend_up/down.
    """
    if z_score is not None and abs(z_score) > Z_THRESHOLD:
        insight_type = "spike" if z_score > 0 else "dip"
        return insight_type, True

    if trend_slope is not None:
        if trend_slope > SLOPE_THRESHOLD:
            return "trend_up", False
        if trend_slope < -SLOPE_THRESHOLD:
            return "trend_down", False

    return "stable", False


def analyze(values: list[float]) -> MathResult:
    """Run all math on a chronological list of KPI values and return a MathResult.

    `values` should be all monthly snapshot values for one KPI, oldest first.
    The last element is the current period being analysed.
    """
    z_score, expected, residual_std = compute_z_score(values)
    rolling_avg_3m = compute_rolling_average(values, 3)
    rolling_avg_6m = compute_rolling_average(values, 6)
    trend_slope = compute_trend_slope(values)
    insight_type, is_anomaly = classify(z_score, trend_slope)

    return MathResult(
        z_score=round(z_score, 4) if z_score is not None else None,
        baseline_mean=round(expected, 4) if expected is not None else None,
        baseline_std=round(residual_std, 4) if residual_std is not None else None,
        rolling_avg_3m=round(rolling_avg_3m, 4) if rolling_avg_3m is not None else None,
        rolling_avg_6m=round(rolling_avg_6m, 4) if rolling_avg_6m is not None else None,
        trend_slope=round(trend_slope, 4) if trend_slope is not None else None,
        insight_type=insight_type,
        is_anomaly=is_anomaly,
    )
