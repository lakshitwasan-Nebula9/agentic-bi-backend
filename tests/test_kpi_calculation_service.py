"""
Unit tests for kpi_calculation_service — monthly bucketing and snapshot routing.
All DB calls are mocked; no real Postgres required.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest
from fastapi import HTTPException

from app.services.kpi_calculation_service import (
    compute_monthly_snapshots,
    snapshot_kpi,
)


def _make_kpi(sql_expression: str = "SUM(total_amount) AS total_revenue") -> MagicMock:
    kpi = MagicMock()
    kpi.id = uuid.uuid4()
    kpi.dataset_id = uuid.uuid4()
    kpi.table_name = "orders"
    kpi.sql_expression = sql_expression
    return kpi


def _make_schema_meta(date_columns: list[str] | None = None) -> MagicMock:
    meta = MagicMock()
    meta.columns = [
        {"name": "total_amount"},
        {"name": "created_at"},
    ]
    meta.date_columns = date_columns or ["created_at"]
    return meta


JAN = datetime(2026, 1, 1, tzinfo=timezone.utc)
FEB = datetime(2026, 2, 1, tzinfo=timezone.utc)
MAR = datetime(2026, 3, 1, tzinfo=timezone.utc)

SUBSTITUTED = "SUM((t.row_data->>'total_amount')::numeric) AS total_revenue"


# ---------------------------------------------------------------------------
# compute_monthly_snapshots
# ---------------------------------------------------------------------------


def _setup_db_for_monthly(db: MagicMock, month_rows, existing_periods, monthly_values):
    """Wire db.execute side-effects: months query first, then one per month."""
    months_result = MagicMock()
    months_result.fetchall.return_value = month_rows

    monthly_results = []
    for val in monthly_values:
        r = MagicMock()
        r.scalar.return_value = val
        monthly_results.append(r)

    db.execute.side_effect = [months_result, *monthly_results]

    existing_query = MagicMock()
    existing_query.filter.return_value.all.return_value = [(p,) for p in existing_periods]
    db.query.return_value = existing_query


def test_monthly_snapshots_creates_one_per_month():
    db = MagicMock()
    kpi = _make_kpi()
    _setup_db_for_monthly(db, [(JAN,), (FEB,)], [], [1000.0, 1500.0])

    with (
        patch("app.services.kpi_calculation_service.validate_sql_expression"),
        patch(
            "app.services.kpi_calculation_service.get_schema_metadata_by_table",
            return_value=_make_schema_meta(),
        ),
        patch(
            "app.services.kpi_calculation_service.get_dataset",
            return_value=MagicMock(schema_fingerprint={"total_amount": "float"}),
        ),
        patch(
            "app.services.kpi_calculation_service._substitute_columns",
            return_value=SUBSTITUTED,
        ),
        patch("app.services.kpi_calculation_service.create_snapshot") as mock_create,
    ):
        mock_create.side_effect = [MagicMock(), MagicMock()]
        result = compute_monthly_snapshots(db, kpi, "created_at")

    assert len(result) == 2
    assert mock_create.call_count == 2

    # Verify period_start values passed to create_snapshot (args: db, kpi_id, dataset_id, value, period_start, period_end)
    jan_call, feb_call = mock_create.call_args_list
    assert jan_call[0][4] == JAN  # period_start for January
    assert feb_call[0][4] == FEB  # period_start for February


def test_monthly_snapshots_skips_existing_periods():
    """Months that already have a snapshot must be skipped (idempotent)."""
    db = MagicMock()
    kpi = _make_kpi()

    # JAN already exists, only FEB is new
    _setup_db_for_monthly(db, [(JAN,), (FEB,)], [JAN], [1500.0])

    with (
        patch("app.services.kpi_calculation_service.validate_sql_expression"),
        patch(
            "app.services.kpi_calculation_service.get_schema_metadata_by_table",
            return_value=_make_schema_meta(),
        ),
        patch(
            "app.services.kpi_calculation_service.get_dataset",
            return_value=MagicMock(schema_fingerprint={}),
        ),
        patch(
            "app.services.kpi_calculation_service._substitute_columns",
            return_value=SUBSTITUTED,
        ),
        patch("app.services.kpi_calculation_service.create_snapshot") as mock_create,
    ):
        mock_create.side_effect = [MagicMock()]
        result = compute_monthly_snapshots(db, kpi, "created_at")

    assert len(result) == 1
    assert mock_create.call_count == 1
    assert mock_create.call_args[0][4] == FEB


def test_monthly_snapshots_returns_empty_when_no_date_rows():
    """Dataset with no parseable date values returns empty list without error."""
    db = MagicMock()
    kpi = _make_kpi()
    _setup_db_for_monthly(db, [], [], [])

    with (
        patch("app.services.kpi_calculation_service.validate_sql_expression"),
        patch(
            "app.services.kpi_calculation_service.get_schema_metadata_by_table",
            return_value=_make_schema_meta(),
        ),
        patch(
            "app.services.kpi_calculation_service.get_dataset",
            return_value=MagicMock(schema_fingerprint={}),
        ),
        patch(
            "app.services.kpi_calculation_service._substitute_columns",
            return_value=SUBSTITUTED,
        ),
        patch("app.services.kpi_calculation_service.create_snapshot") as mock_create,
    ):
        result = compute_monthly_snapshots(db, kpi, "created_at")

    assert result == []
    mock_create.assert_not_called()


def test_monthly_snapshots_period_end_is_last_moment_of_month():
    """period_end must be the last microsecond of the month, not first of next."""
    from datetime import timedelta

    db = MagicMock()
    kpi = _make_kpi()
    _setup_db_for_monthly(db, [(JAN,)], [], [500.0])

    captured_calls = []

    def capture_create(db, kpi_id, dataset_id, value, period_start, period_end):
        captured_calls.append((period_start, period_end))
        return MagicMock()

    with (
        patch("app.services.kpi_calculation_service.validate_sql_expression"),
        patch(
            "app.services.kpi_calculation_service.get_schema_metadata_by_table",
            return_value=_make_schema_meta(),
        ),
        patch(
            "app.services.kpi_calculation_service.get_dataset",
            return_value=MagicMock(schema_fingerprint={}),
        ),
        patch(
            "app.services.kpi_calculation_service._substitute_columns",
            return_value=SUBSTITUTED,
        ),
        patch(
            "app.services.kpi_calculation_service.create_snapshot",
            side_effect=capture_create,
        ),
    ):
        compute_monthly_snapshots(db, kpi, "created_at")

    period_start, period_end = captured_calls[0]
    expected_end = FEB - timedelta(microseconds=1)
    assert period_start == JAN
    assert period_end == expected_end


def test_monthly_snapshots_december_wraps_to_january():
    """December period_end must wrap to Jan 1 of next year minus 1 microsecond."""
    from datetime import timedelta

    dec = datetime(2026, 12, 1, tzinfo=timezone.utc)
    db = MagicMock()
    kpi = _make_kpi()
    _setup_db_for_monthly(db, [(dec,)], [], [999.0])

    captured = []

    def capture_create(db, kpi_id, dataset_id, value, period_start, period_end):
        captured.append((period_start, period_end))
        return MagicMock()

    with (
        patch("app.services.kpi_calculation_service.validate_sql_expression"),
        patch(
            "app.services.kpi_calculation_service.get_schema_metadata_by_table",
            return_value=_make_schema_meta(),
        ),
        patch(
            "app.services.kpi_calculation_service.get_dataset",
            return_value=MagicMock(schema_fingerprint={}),
        ),
        patch(
            "app.services.kpi_calculation_service._substitute_columns",
            return_value=SUBSTITUTED,
        ),
        patch(
            "app.services.kpi_calculation_service.create_snapshot",
            side_effect=capture_create,
        ),
    ):
        compute_monthly_snapshots(db, kpi, "created_at")

    _, period_end = captured[0]
    jan_next = datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert period_end == jan_next - timedelta(microseconds=1)


def test_monthly_snapshots_sql_error_skips_month_continues():
    """A SQL failure on one month must not abort processing of subsequent months."""
    db = MagicMock()
    kpi = _make_kpi()

    months_result = MagicMock()
    months_result.fetchall.return_value = [(JAN,), (FEB,), (MAR,)]

    jan_fail = MagicMock()
    jan_fail.scalar.side_effect = RuntimeError("bad cast")
    feb_ok = MagicMock()
    feb_ok.scalar.return_value = 1500.0
    mar_ok = MagicMock()
    mar_ok.scalar.return_value = 2000.0

    db.execute.side_effect = [months_result, jan_fail, feb_ok, mar_ok]
    existing_query = MagicMock()
    existing_query.filter.return_value.all.return_value = []
    db.query.return_value = existing_query

    with (
        patch("app.services.kpi_calculation_service.validate_sql_expression"),
        patch(
            "app.services.kpi_calculation_service.get_schema_metadata_by_table",
            return_value=_make_schema_meta(),
        ),
        patch(
            "app.services.kpi_calculation_service.get_dataset",
            return_value=MagicMock(schema_fingerprint={}),
        ),
        patch(
            "app.services.kpi_calculation_service._substitute_columns",
            return_value=SUBSTITUTED,
        ),
        patch("app.services.kpi_calculation_service.create_snapshot") as mock_create,
    ):
        mock_create.side_effect = [MagicMock(), MagicMock()]
        result = compute_monthly_snapshots(db, kpi, "created_at")

    assert len(result) == 2
    assert mock_create.call_count == 2


def test_monthly_snapshots_invalid_sql_raises_422():
    db = MagicMock()
    kpi = _make_kpi(sql_expression="DROP TABLE kpi_definitions")

    with patch(
        "app.services.kpi_calculation_service.validate_sql_expression",
        side_effect=ValueError("forbidden keyword"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            compute_monthly_snapshots(db, kpi, "created_at")

    assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# snapshot_kpi routing
# ---------------------------------------------------------------------------


def test_snapshot_kpi_routes_to_monthly_when_date_columns_exist():
    db = MagicMock()
    kpi = _make_kpi()
    schema_meta = _make_schema_meta(date_columns=["created_at"])

    fake_snapshots = [MagicMock(), MagicMock()]

    with (
        patch(
            "app.services.kpi_calculation_service.get_schema_metadata_by_table",
            return_value=schema_meta,
        ),
        patch(
            "app.services.kpi_calculation_service.compute_monthly_snapshots",
            return_value=fake_snapshots,
        ) as mock_monthly,
        patch("app.services.kpi_calculation_service.compute_and_snapshot") as mock_full,
    ):
        result = snapshot_kpi(db, kpi)

    mock_monthly.assert_called_once_with(db, kpi, "created_at")
    mock_full.assert_not_called()
    assert result is fake_snapshots


def test_snapshot_kpi_falls_back_to_full_dataset_when_no_date_columns():
    db = MagicMock()
    kpi = _make_kpi()
    schema_meta = _make_schema_meta(date_columns=None)
    schema_meta.date_columns = None
    fake_snap = MagicMock()

    with (
        patch(
            "app.services.kpi_calculation_service.get_schema_metadata_by_table",
            return_value=schema_meta,
        ),
        patch(
            "app.services.kpi_calculation_service.compute_monthly_snapshots"
        ) as mock_monthly,
        patch(
            "app.services.kpi_calculation_service.compute_and_snapshot",
            return_value=fake_snap,
        ) as mock_full,
    ):
        result = snapshot_kpi(db, kpi)

    mock_monthly.assert_not_called()
    mock_full.assert_called_once_with(db, kpi)
    assert result == [fake_snap]


def test_snapshot_kpi_falls_back_when_monthly_returns_empty():
    """If date columns exist but monthly returns nothing, fall back to full-dataset."""
    db = MagicMock()
    kpi = _make_kpi()
    schema_meta = _make_schema_meta(date_columns=["created_at"])
    fake_snap = MagicMock()

    with (
        patch(
            "app.services.kpi_calculation_service.get_schema_metadata_by_table",
            return_value=schema_meta,
        ),
        patch(
            "app.services.kpi_calculation_service.compute_monthly_snapshots",
            return_value=[],
        ),
        patch(
            "app.services.kpi_calculation_service.compute_and_snapshot",
            return_value=fake_snap,
        ) as mock_full,
    ):
        result = snapshot_kpi(db, kpi)

    mock_full.assert_called_once_with(db, kpi)
    assert result == [fake_snap]
