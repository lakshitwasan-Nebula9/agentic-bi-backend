"""
Seed script — populates the second sample-data source (`db2` service, the
`retail_analytics` database on localhost:5433) with a `sales_transactions`
table spanning Jan 1 – Jun 30 2026 (~1 200 rows).

This is a *different domain* than the `db` service's support_tickets, so the app
can register two connectors at once and preconfigure dashboards from either.

Usage:
    docker compose up -d db2
    python scripts/seed_db2_retail.py

Requires the db2 Postgres running on localhost:5433.
"""

import random
from datetime import UTC, datetime, timedelta

import psycopg2

# ── Config ────────────────────────────────────────────────────────────────────
TARGET_DSN = "postgresql://user:password@localhost:5433/retail_analytics"

START = datetime(2026, 1, 1, tzinfo=UTC)
END = datetime(2026, 6, 30, tzinfo=UTC)

PRODUCT_CATEGORIES = ["electronics", "apparel", "home", "beauty", "sports", "grocery"]
CATEGORY_PRICE = {
    "electronics": (80, 600),
    "apparel": (15, 120),
    "home": (25, 300),
    "beauty": (8, 90),
    "sports": (20, 250),
    "grocery": (5, 60),
}
REGIONS = ["north", "south", "east", "west", "central"]
CHANNELS = ["online", "in_store", "marketplace", "mobile_app"]
PAYMENT_METHODS = ["card", "upi", "wallet", "cod", "netbanking"]

random.seed(7)


def rand_dt(start: datetime, end: datetime) -> datetime:
    delta = end - start
    secs = random.randint(0, int(delta.total_seconds()))
    return start + timedelta(seconds=secs)


def build_txn(txn_id: int) -> dict:
    order_date = rand_dt(START, END)
    category = random.choice(PRODUCT_CATEGORIES)
    low, high = CATEGORY_PRICE[category]
    unit_price = round(random.uniform(low, high), 2)
    quantity = random.choices([1, 2, 3, 4, 5], weights=[0.5, 0.25, 0.13, 0.08, 0.04])[0]
    revenue = round(unit_price * quantity, 2)
    # Cost is 55–80% of revenue → margin varies by transaction.
    cost = round(revenue * random.uniform(0.55, 0.80), 2)
    profit = round(revenue - cost, 2)
    is_returned = random.random() < 0.06  # ~6% return rate

    return {
        "transaction_id": txn_id,
        "order_date": order_date,
        "customer_id": random.randint(2000, 9000),
        "product_category": category,
        "region": random.choice(REGIONS),
        "channel": random.choice(CHANNELS),
        "payment_method": random.choice(PAYMENT_METHODS),
        "quantity": quantity,
        "unit_price": unit_price,
        "revenue": revenue,
        "cost": cost,
        "profit": profit,
        "is_returned": is_returned,
    }


def main() -> None:
    conn = psycopg2.connect(TARGET_DSN)
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sales_transactions (
                transaction_id   INTEGER PRIMARY KEY,
                order_date       TIMESTAMPTZ NOT NULL,
                customer_id      INTEGER NOT NULL,
                product_category TEXT NOT NULL,
                region           TEXT NOT NULL,
                channel          TEXT NOT NULL,
                payment_method   TEXT NOT NULL,
                quantity         INTEGER NOT NULL,
                unit_price       NUMERIC(10,2) NOT NULL,
                revenue          NUMERIC(12,2) NOT NULL,
                cost             NUMERIC(12,2) NOT NULL,
                profit           NUMERIC(12,2) NOT NULL,
                is_returned      BOOLEAN NOT NULL
            )
            """
        )
        conn.commit()
        print("Table 'sales_transactions' ready")

        cur.execute("DELETE FROM sales_transactions")

        txns = [build_txn(i) for i in range(1, 1201)]
        cur.executemany(
            """
            INSERT INTO sales_transactions (
                transaction_id, order_date, customer_id, product_category,
                region, channel, payment_method, quantity, unit_price,
                revenue, cost, profit, is_returned
            ) VALUES (
                %(transaction_id)s, %(order_date)s, %(customer_id)s, %(product_category)s,
                %(region)s, %(channel)s, %(payment_method)s, %(quantity)s, %(unit_price)s,
                %(revenue)s, %(cost)s, %(profit)s, %(is_returned)s
            )
            """,
            txns,
        )
        conn.commit()

    conn.close()
    print(f"Inserted {len(txns)} sales_transactions rows")
    print()
    print("Connect via the app with:")
    print("  host=localhost  port=5433  database=retail_analytics")
    print("  username=user  password=password")


if __name__ == "__main__":
    main()
