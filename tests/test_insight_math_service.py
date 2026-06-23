"""Tests for insight_math_service — pure math, no DB."""

import pytest

from app.services.insight_math_service import (
    MathResult,
    analyze,
    classify,
    compute_rolling_average,
    compute_trend_slope,
    compute_z_score,
)

# ---------------------------------------------------------------------------
# compute_z_score
# ---------------------------------------------------------------------------


def test_z_score_positive_spike():
    # baseline: [100, 100, 100, 100] → mean=100, std=0... use varied baseline
    values = [100.0, 105.0, 98.0, 102.0, 300.0]  # last value is a spike
    z, mean, std = compute_z_score(values)
    assert z is not None and z > 2.0


def test_z_score_negative_dip():
    values = [100.0, 105.0, 98.0, 102.0, 10.0]  # last value is a dip
    z, mean, std = compute_z_score(values)
    assert z is not None and z < -2.0


def test_z_score_normal_value():
    values = [100.0, 102.0, 99.0, 101.0, 100.5]
    z, mean, std = compute_z_score(values)
    assert z is not None and abs(z) < 2.0


def test_z_score_too_few_values():
    z, mean, std = compute_z_score([100.0, 200.0])
    assert z is None and mean is None and std is None


def test_z_score_needs_four_values():
    # Detrended z needs >= 3 history points (>= 4 total) to estimate residual spread.
    z, mean, std = compute_z_score([100.0, 110.0, 140.0])
    assert z is None


def test_z_score_detrended_ignores_linear_trend():
    # A perfectly linear series has zero residual spread → no anomaly to report.
    z, expected, residual_std = compute_z_score([100.0, 120.0, 140.0, 160.0, 180.0])
    assert z is None
    assert expected == pytest.approx(180.0)  # trend predicts the actual value
    assert residual_std == pytest.approx(0.0)


def test_z_score_zero_std_returns_none():
    # All baseline values identical → std=0
    values = [100.0, 100.0, 100.0, 100.0]
    z, mean, std = compute_z_score(values)
    assert z is None
    assert mean == 100.0
    assert std == 0.0


# ---------------------------------------------------------------------------
# compute_rolling_average
# ---------------------------------------------------------------------------


def test_rolling_average_3m():
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    avg = compute_rolling_average(values, 3)
    assert avg == pytest.approx((30.0 + 40.0 + 50.0) / 3)


def test_rolling_average_6m():
    values = [10.0, 20.0, 30.0]
    avg = compute_rolling_average(values, 6)
    assert avg is None  # fewer values than window


def test_rolling_average_exact_window():
    values = [10.0, 20.0, 30.0]
    avg = compute_rolling_average(values, 3)
    assert avg == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# compute_trend_slope
# ---------------------------------------------------------------------------


def test_trend_slope_upward():
    values = [100.0, 110.0, 120.0, 130.0, 140.0]
    slope = compute_trend_slope(values)
    assert slope is not None and slope > 0


def test_trend_slope_downward():
    values = [140.0, 130.0, 120.0, 110.0, 100.0]
    slope = compute_trend_slope(values)
    assert slope is not None and slope < 0


def test_trend_slope_flat():
    values = [100.0, 100.0, 100.0, 100.0, 100.0]
    slope = compute_trend_slope(values)
    assert slope == pytest.approx(0.0, abs=1e-6)


def test_trend_slope_too_few_values():
    slope = compute_trend_slope([100.0, 200.0])
    assert slope is None


def test_trend_slope_zero_mean_returns_none():
    values = [0.0, 0.0, 0.0, 0.0]
    slope = compute_trend_slope(values)
    assert slope is None


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------


def test_classify_spike():
    insight_type, is_anomaly = classify(z_score=2.5, trend_slope=None)
    assert insight_type == "spike" and is_anomaly is True


def test_classify_dip():
    insight_type, is_anomaly = classify(z_score=-3.1, trend_slope=None)
    assert insight_type == "dip" and is_anomaly is True


def test_classify_trend_up():
    insight_type, is_anomaly = classify(z_score=1.0, trend_slope=8.0)
    assert insight_type == "trend_up" and is_anomaly is False


def test_classify_trend_down():
    insight_type, is_anomaly = classify(z_score=-1.0, trend_slope=-7.0)
    assert insight_type == "trend_down" and is_anomaly is False


def test_classify_stable():
    insight_type, is_anomaly = classify(z_score=0.5, trend_slope=2.0)
    assert insight_type == "stable" and is_anomaly is False


def test_classify_anomaly_takes_priority_over_trend():
    # Even a strong trend slope, if z_score is anomalous, it should be spike/dip
    insight_type, is_anomaly = classify(z_score=3.0, trend_slope=20.0)
    assert insight_type == "spike" and is_anomaly is True


# ---------------------------------------------------------------------------
# analyze (integration of all math steps)
# ---------------------------------------------------------------------------


def test_analyze_returns_math_result():
    values = [100.0, 105.0, 98.0, 102.0, 99.0, 101.0]
    result = analyze(values)
    assert isinstance(result, MathResult)
    assert result.insight_type in ("spike", "dip", "trend_up", "trend_down", "stable")
    assert isinstance(result.is_anomaly, bool)


def test_analyze_spike_detected():
    values = [100.0, 102.0, 99.0, 101.0, 100.0, 500.0]
    result = analyze(values)
    assert result.insight_type == "spike"
    assert result.is_anomaly is True
    assert result.z_score is not None and result.z_score > 2.0


def test_analyze_dip_detected():
    values = [100.0, 102.0, 99.0, 101.0, 100.0, 5.0]
    result = analyze(values)
    assert result.insight_type == "dip"
    assert result.is_anomaly is True


def test_analyze_linear_growth_is_trend_not_anomaly():
    # Regression test: a steady linear trend must NOT be flagged as a spike.
    values = [100.0, 120.0, 140.0, 160.0, 180.0, 200.0, 220.0]
    result = analyze(values)
    assert result.insight_type == "trend_up"
    assert result.is_anomaly is False
    assert result.trend_slope is not None and result.trend_slope > 0


def test_analyze_steady_decline_is_trend_down():
    values = [200.0, 185.0, 170.0, 155.0, 140.0, 125.0, 110.0]
    result = analyze(values)
    assert result.insight_type == "trend_down"
    assert result.is_anomaly is False
    assert result.trend_slope is not None and result.trend_slope < 0


def test_analyze_rolling_avgs_populated():
    values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
    result = analyze(values)
    assert result.rolling_avg_3m == pytest.approx((40.0 + 50.0 + 60.0) / 3)
    assert result.rolling_avg_6m == pytest.approx(sum(values) / 6)


def test_analyze_too_few_snapshots_returns_nones():
    values = [100.0, 200.0]
    result = analyze(values)
    assert result.z_score is None
    assert result.rolling_avg_3m is None
    assert result.trend_slope is None
    assert result.insight_type == "stable"
    assert result.is_anomaly is False


def test_analyze_rounding():
    values = [100.123456789, 200.987654321, 150.111111111, 175.0]
    result = analyze(values)
    if result.z_score is not None:
        assert len(str(result.z_score).split(".")[-1]) <= 4
