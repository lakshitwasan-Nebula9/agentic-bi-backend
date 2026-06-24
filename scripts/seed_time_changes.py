"""
Seed script — creates the `time_changes` table in the local source DB with 14 months
of data (April 2025 – May 2026) for testing time intelligence features:
  - YoY  (needs ≥13 months)
  - QoQ  (needs ≥4 months)
  - YTD  (needs ≥1 snapshot in current year)

After running this script:
  1. In the app, connect time_changes as a new dataset via the connector UI
  2. Trigger KPI generation  →  POST /api/v1/datasets/{id}/kpis/generate
  3. Hit GET /api/v1/kpis to see yoy_change_pct, qoq_change_pct, ytd_value

Usage:
    python scripts/seed_time_changes.py

Requires local Postgres on localhost:5432.
"""

import random
from datetime import UTC, datetime, timedelta

import psycopg2

DSN = "postgresql://user:password@localhost:5432/agentic_bi"

START = datetime(2025, 4, 1, tzinfo=UTC)
END = datetime(2026, 5, 31, 23, 59, 59, tzinfo=UTC)

ORDERS_PER_MONTH = 300
random.seed(99)


def rand_dt(month_start: datetime, month_end: datetime) -> datetime:
    delta = int((month_end - month_start).total_seconds())
    return month_start + timedelta(seconds=random.randint(0, delta))


def month_range(start: datetime, end: datetime):
    cur = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while cur <= end:
        if cur.month == 12:
            next_month = cur.replace(year=cur.year + 1, month=1)
        else:
            next_month = cur.replace(month=cur.month + 1)
        month_end = next_month - timedelta(seconds=1)
        yield cur, min(month_end, end)
        cur = next_month


def build_rows(month_start: datetime, month_end: datetime, id_offset: int) -> list[dict]:
    month = month_start.month
    if month in (11, 12):
        volume_mult = random.uniform(1.3, 1.5)
    elif month in (1, 2):
        volume_mult = random.uniform(0.8, 0.95)
    elif month in (6, 7, 8):
        volume_mult = random.uniform(1.05, 1.2)
    else:
        volume_mult = random.uniform(0.95, 1.1)

    count = max(100, int(ORDERS_PER_MONTH * volume_mult))
    rows = []
    for i in range(count):
        item_count = random.choices([1, 2, 3, 4, 5, 6, 7, 8], weights=[30, 25, 20, 12, 7, 3, 2, 1])[
            0
        ]
        base_price = random.uniform(40, 200) * item_count
        discount_pct = random.choices([0, 0.05, 0.10, 0.15, 0.20], weights=[40, 20, 20, 12, 8])[0]
        rows.append(
            {
                "order_id": id_offset + i,
                "customer_id": random.randint(1000, 9999),
                "order_date": rand_dt(month_start, month_end),
                "total_amount": round(base_price, 2),
                "discount_amount": round(base_price * discount_pct, 2),
                "item_count": item_count,
            }
        )
    return rows


def main() -> None:
    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS time_changes")
        cur.execute(
            """
            CREATE TABLE time_changes (
                order_id        INTEGER PRIMARY KEY,
                customer_id     INTEGER NOT NULL,
                order_date      TIMESTAMPTZ NOT NULL,
                total_amount    NUMERIC(10,2) NOT NULL,
                discount_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
                item_count      INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        conn.commit()
        print("Table 'time_changes' created.")

        total_rows = 0
        id_offset = 1
        months = list(month_range(START, END))

        for month_start, month_end in months:
            rows = build_rows(month_start, month_end, id_offset)
            cur.executemany(
                """
                INSERT INTO time_changes
                    (order_id, customer_id, order_date, total_amount, discount_amount, item_count)
                VALUES
                    (%(order_id)s, %(customer_id)s, %(order_date)s,
                     %(total_amount)s, %(discount_amount)s, %(item_count)s)
                """,
                rows,
            )
            conn.commit()
            id_offset += len(rows)
            total_rows += len(rows)
            label = month_start.strftime("%b %Y")
            net = sum(r["total_amount"] - r["discount_amount"] for r in rows)
            print(f"  {label}: {len(rows):>4} rows  |  net revenue ≈ ${net:>10,.0f}")

        conn.close()

    print()
    print(
        f"Done. Inserted {total_rows:,} rows across {len(months)} months ({START:%b %Y} – {END:%b %Y})."
    )
    print()
    print("Next steps:")
    print(
        "  1. Connect 'time_changes' as a new dataset in the app (use the existing PostgreSQL connector)"
    )
    print("  2. Generate KPIs  →  POST /api/v1/datasets/{dataset_id}/kpis/generate")
    print(
        "  3. Certify the KPIs, then GET /api/v1/kpis to see yoy_change_pct, qoq_change_pct, ytd_value"
    )


if __name__ == "__main__":
    main()
