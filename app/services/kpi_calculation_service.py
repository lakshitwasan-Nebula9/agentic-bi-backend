"""
KPI Calculation Service — executes LLM-generated SQL aggregations against
dataset_records (JSONB store) and snapshots the result.

SQL safety: only a whitelisted set of aggregate functions is permitted in
sql_expression; no DML, DDL, subqueries, or CASE/WHEN allowed at MVP.
Recompute path is included as a first-class operation so dataset refreshes
can trigger a new snapshot without re-running the KPI Agent.
"""

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.crud.dataset import get_dataset
from app.crud.kpi import create_snapshot
from app.crud.schema_metadata import get_schema_metadata_by_table
from app.models.kpi import KPIDefinition, KPISnapshot

logger = logging.getLogger(__name__)

_FORBIDDEN = re.compile(
    r"\b(SELECT|FROM|WHERE|JOIN|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|"
    r"TRUNCATE|EXEC|EXECUTE|UNION)\b|;",
    re.IGNORECASE,
)

_ALLOWED_AGGREGATE_PREFIX = re.compile(
    r"^\s*(SUM|COUNT|AVG|MIN|MAX|ROUND|COALESCE|CASE)\s*[\s(]",
    re.IGNORECASE,
)

# Python type names from schema_fingerprint that map to numeric
_NUMERIC_TYPES = {"int", "float", "Decimal", "complex"}
_BOOL_TYPES = {"bool"}
_TEXT_TYPES = {"str"}


def validate_sql_expression(sql_expression: str) -> None:
    """Raise ValueError if sql_expression contains disallowed SQL constructs."""
    expr_only = re.split(r"\s+AS\s+", sql_expression, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    if _FORBIDDEN.search(sql_expression):
        raise ValueError(
            f"sql_expression contains a forbidden SQL keyword or semicolon: {sql_expression!r}"
        )
    if not _ALLOWED_AGGREGATE_PREFIX.match(expr_only):
        raise ValueError(
            f"sql_expression must begin with an allowed aggregate function "
            f"(SUM, COUNT, AVG, MIN, MAX, ROUND, COALESCE): {sql_expression!r}"
        )


def _jsonb_accessor(col: str, py_type: str) -> str:
    """Return the correct JSONB accessor for a column given its Python type name."""
    if py_type in _BOOL_TYPES:
        # Cast to boolean so CASE WHEN col = TRUE / CASE WHEN col both work.
        # AVG/SUM on ::boolean is invalid in PG — fixed by _fix_bool_aggregates() below.
        return f"(t.row_data->>'{col}')::boolean"
    if py_type in _NUMERIC_TYPES:
        return f"(t.row_data->>'{col}')::numeric"
    # Text, identifiers, dimensions, ISO-string datetimes — raw text; COUNT works fine
    return f"(t.row_data->>'{col}')"


def _fix_bool_aggregates(expr: str) -> str:
    """PostgreSQL has no AVG/SUM for boolean. Cast ::boolean to ::int where needed."""
    return re.sub(
        r"\b(AVG|SUM)\s*\(([^()]*::boolean)\)",
        lambda m: f"{m.group(1)}(({m.group(2)})::int)",
        expr,
        flags=re.IGNORECASE,
    )


def _substitute_columns(
    sql_expression: str,
    column_names: list[str],
    column_types: dict[str, str] | None = None,
) -> str:
    """Replace bare column name references with type-aware JSONB accessors."""
    parts = re.split(r"\s+AS\s+", sql_expression, maxsplit=1, flags=re.IGNORECASE)
    expr = parts[0]
    alias = (" AS " + parts[1]) if len(parts) > 1 else ""

    for col in sorted(column_names, key=len, reverse=True):
        py_type = (column_types or {}).get(col, "")
        accessor = _jsonb_accessor(col, py_type)
        pattern = r"\b" + re.escape(col) + r"\b"
        expr = re.sub(pattern, accessor, expr)

    # Fix AVG/SUM on ::boolean (PG has no boolean aggregate) → cast to int
    expr = _fix_bool_aggregates(expr)

    # PostgreSQL ROUND(x, n) requires x::numeric — wrap first arg defensively
    expr = re.sub(
        r"\bROUND\s*\((.+?),\s*(\d+)\)",
        lambda m: f"ROUND(({m.group(1)})::numeric, {m.group(2)})",
        expr,
        flags=re.IGNORECASE,
    )

    return expr + alias


def derive_snapshot_period(
    db: Session, dataset_id: uuid.UUID, table_name: str
) -> tuple[datetime | None, datetime | None]:
    """Query MIN/MAX of the first date column in dataset_records to derive a snapshot period.

    Returns (None, None) when no date columns exist or the column cannot be cast to a timestamp.
    """
    schema_meta = get_schema_metadata_by_table(db, table_name)
    if not schema_meta or not schema_meta.date_columns:
        return None, None

    date_cols = schema_meta.date_columns
    if not date_cols:
        return None, None

    date_col = date_cols[0] if isinstance(date_cols, list) else next(iter(date_cols))

    sql = text(
        "SELECT "
        "  MIN((t.row_data->>:col)::timestamp with time zone) AS period_start, "
        "  MAX((t.row_data->>:col)::timestamp with time zone) AS period_end "
        "FROM dataset_records t "
        "WHERE t.dataset_id = :dataset_id "
        "  AND t.row_data->>:col IS NOT NULL"
    )
    try:
        row = db.execute(sql, {"col": date_col, "dataset_id": str(dataset_id)}).fetchone()
        if row and row[0] is not None:
            return row[0], row[1]
    except Exception:
        logger.warning(
            "Could not derive snapshot period for dataset %s col '%s'",
            dataset_id,
            date_col,
            exc_info=True,
        )
    return None, None


def compute_monthly_snapshots(
    db: Session,
    kpi: KPIDefinition,
    date_col: str,
) -> list[KPISnapshot]:
    """Execute kpi.sql_expression independently per calendar month bucket.

    Each month's records are isolated before aggregation so non-additive metrics
    (AVG, COUNT DISTINCT, rates) are computed correctly within their period.
    Months that already have a snapshot for this KPI are skipped (idempotent).
    Returns an empty list when the dataset has no parseable date values.
    """
    try:
        validate_sql_expression(kpi.sql_expression)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    schema_meta = get_schema_metadata_by_table(db, kpi.table_name)
    column_names: list[str] = []
    if schema_meta and schema_meta.columns:
        column_names = [col["name"] for col in schema_meta.columns if isinstance(col, dict)]

    column_types: dict[str, str] = {}
    dataset = get_dataset(db, kpi.dataset_id)
    if dataset and dataset.schema_fingerprint:
        column_types = dataset.schema_fingerprint

    substituted = _substitute_columns(kpi.sql_expression, column_names, column_types)

    # Discover distinct calendar months present in the dataset
    months_sql = text(
        "SELECT DISTINCT date_trunc('month', (row_data->>:col)::timestamptz) AS month_start "
        "FROM dataset_records "
        "WHERE dataset_id = :dataset_id AND row_data->>:col IS NOT NULL "
        "ORDER BY month_start"
    )
    try:
        month_rows = db.execute(
            months_sql, {"col": date_col, "dataset_id": str(kpi.dataset_id)}
        ).fetchall()
    except Exception as exc:
        logger.warning(
            "Could not discover monthly buckets for KPI %s col '%s': %s", kpi.id, date_col, exc
        )
        return []

    if not month_rows:
        return []

    # Fetch already-snapshotted period_starts for this KPI to skip completed months
    existing_period_starts: set[datetime] = {
        row[0]
        for row in db.query(KPISnapshot.period_start)
        .filter(KPISnapshot.kpi_id == kpi.id, KPISnapshot.period_start.isnot(None))
        .all()
    }

    # JSONB accessor used in the monthly WHERE clause (date_col comes from trusted schema metadata)
    date_accessor = f"(row_data->>'{date_col}')::timestamptz"

    snapshots: list[KPISnapshot] = []
    for (month_start,) in month_rows:
        if month_start.tzinfo is None:
            month_start = month_start.replace(tzinfo=timezone.utc)

        if month_start in existing_period_starts:
            continue

        # period_end = last microsecond of the month (inclusive upper bound)
        if month_start.month == 12:
            next_month = month_start.replace(
                year=month_start.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0
            )
        else:
            next_month = month_start.replace(
                month=month_start.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0
            )
        period_end = next_month - timedelta(microseconds=1)

        # Run KPI expression against this month's records only
        monthly_sql = (
            f"SELECT {substituted} FROM ("
            f"  SELECT row_data FROM dataset_records "
            f"  WHERE dataset_id = :dataset_id "
            f"    AND {date_accessor} >= :bucket_start "
            f"    AND {date_accessor} <= :bucket_end"
            f") AS t"
        )
        try:
            result = db.execute(
                text(monthly_sql),
                {
                    "dataset_id": str(kpi.dataset_id),
                    "bucket_start": month_start,
                    "bucket_end": period_end,
                },
            ).scalar()
        except Exception as exc:
            logger.warning(
                "Monthly KPI SQL failed for %s period %s: %s", kpi.id, month_start, exc
            )
            continue

        if result is None:
            continue

        snap = create_snapshot(db, kpi.id, kpi.dataset_id, float(result), month_start, period_end)
        snapshots.append(snap)

    logger.info("Created %d monthly snapshots for KPI %s", len(snapshots), kpi.id)
    return snapshots


def snapshot_kpi(db: Session, kpi: KPIDefinition) -> list[KPISnapshot]:
    """Route KPI snapshotting: monthly buckets when a date column exists, full-dataset otherwise.

    Returns a list so callers handle both paths uniformly.
    Full-dataset fallback returns a one-element list.
    """
    schema_meta = get_schema_metadata_by_table(db, kpi.table_name)
    date_cols = schema_meta.date_columns if schema_meta else None

    if date_cols:
        date_col = date_cols[0] if isinstance(date_cols, list) else next(iter(date_cols))
        snapshots = compute_monthly_snapshots(db, kpi, date_col)
        if snapshots:
            return snapshots
        logger.warning(
            "Monthly bucketing produced no snapshots for KPI %s — falling back to full-dataset",
            kpi.id,
        )

    return [compute_and_snapshot(db, kpi)]


def compute_and_snapshot(
    db: Session,
    kpi: KPIDefinition,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> KPISnapshot:  # raises HTTPException(422) if dataset has no records
    """Execute kpi.sql_expression against dataset_records and write a KPISnapshot."""
    try:
        validate_sql_expression(kpi.sql_expression)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    schema_meta = get_schema_metadata_by_table(db, kpi.table_name)
    column_names: list[str] = []
    if schema_meta and schema_meta.columns:
        column_names = [col["name"] for col in schema_meta.columns if isinstance(col, dict)]

    # Fetch column types from the dataset's schema_fingerprint for type-aware casting
    column_types: dict[str, str] = {}
    dataset = get_dataset(db, kpi.dataset_id)
    if dataset and dataset.schema_fingerprint:
        column_types = dataset.schema_fingerprint  # {col_name: python_type_name}

    substituted = _substitute_columns(kpi.sql_expression, column_names, column_types)
    sql = (
        f"SELECT {substituted} FROM "
        "(SELECT row_data FROM dataset_records WHERE dataset_id = :dataset_id) AS t"
    )

    try:
        result = db.execute(text(sql), {"dataset_id": str(kpi.dataset_id)}).scalar()
    except Exception as exc:
        logger.error("KPI SQL execution failed for %s: %s — sql=%r", kpi.id, exc, sql)
        raise HTTPException(
            status_code=422,
            detail=f"KPI SQL execution failed: {exc}",
        ) from exc

    if result is None:
        raise HTTPException(
            status_code=422,
            detail=f"KPI '{kpi.name}': SQL returned no result — no dataset_records found for dataset {kpi.dataset_id}",
        )

    # Auto-derive period from schema date columns when caller did not supply one
    if period_start is None and period_end is None:
        period_start, period_end = derive_snapshot_period(db, kpi.dataset_id, kpi.table_name)

    return create_snapshot(db, kpi.id, kpi.dataset_id, float(result), period_start, period_end)


def recompute_snapshot(
    db: Session,
    kpi_id: uuid.UUID,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> KPISnapshot:
    """Recompute a KPI snapshot on demand — called when the underlying dataset is refreshed."""
    from app.crud.kpi import get_kpi

    kpi = get_kpi(db, kpi_id)
    if kpi is None:
        raise HTTPException(status_code=404, detail=f"KPI {kpi_id} not found")

    return compute_and_snapshot(db, kpi, period_start=period_start, period_end=period_end)
