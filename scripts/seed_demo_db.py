"""
Seed script — creates a local `demo_analytics` PostgreSQL database with a
support_tickets table spanning Jan 1 – Jun 19 2026 (~1 100 rows).

Usage:
    python scripts/seed_demo_db.py

Requires a local Postgres running on localhost:5432.
Adjust ADMIN_DSN if your superuser credentials differ.
"""

import random
from datetime import UTC, datetime, timedelta

import psycopg2

# ── Config ────────────────────────────────────────────────────────────────────
TARGET_DSN = "postgresql://user:password@localhost:5432/agentic_bi"

START = datetime(2026, 1, 1, tzinfo=UTC)
END = datetime(2026, 6, 19, tzinfo=UTC)

CATEGORIES = ["billing", "technical", "account", "shipping", "general"]
PRIORITIES = ["low", "medium", "high", "critical"]
PRIORITY_WEIGHTS = [0.40, 0.35, 0.20, 0.05]
AGENTS = [f"agent_{i:02d}" for i in range(1, 9)]
REGIONS = ["north", "south", "east", "west", "central"]
CHANNELS = ["email", "chat", "phone", "portal"]

# SLA target hours by priority
SLA_HOURS = {"low": 72, "medium": 24, "high": 8, "critical": 2}

# Resolution time distributions (mean hours, std) by priority
RESOLUTION_DIST = {
    "low": (48, 20),
    "medium": (16, 8),
    "high": (5, 2),
    "critical": (1.5, 0.8),
}

random.seed(42)


def rand_dt(start: datetime, end: datetime) -> datetime:
    delta = end - start
    secs = random.randint(0, int(delta.total_seconds()))
    return start + timedelta(seconds=secs)


def build_ticket(ticket_id: int) -> dict:
    created_at = rand_dt(START, END)
    priority = random.choices(PRIORITIES, weights=PRIORITY_WEIGHTS)[0]
    category = random.choice(CATEGORIES)
    agent_id = random.choice(AGENTS)
    region = random.choice(REGIONS)
    channel = random.choice(CHANNELS)
    customer_id = random.randint(1000, 5000)

    mean_h, std_h = RESOLUTION_DIST[priority]
    resolution_hours = max(0.5, random.gauss(mean_h, std_h))
    sla_met = resolution_hours <= SLA_HOURS[priority]

    # Tickets created in the last 5 days have a chance to still be open
    days_old = (END - created_at).days
    if days_old < 5 and random.random() < 0.35:
        status = random.choice(["open", "in_progress"])
        resolved_at = None
        satisfaction_score = None
        resolution_hours_val = None
    else:
        status = random.choices(["resolved", "closed"], weights=[0.3, 0.7])[0]
        resolved_at = created_at + timedelta(hours=resolution_hours)
        if resolved_at > END:
            resolved_at = END
        resolution_hours_val = round(resolution_hours, 2)
        # Satisfied customers rate higher; high-priority resolutions skew lower
        base = 4.0 if sla_met else 3.0
        satisfaction_score = min(5, max(1, round(random.gauss(base, 0.8))))

    return {
        "ticket_id": ticket_id,
        "created_at": created_at,
        "resolved_at": resolved_at,
        "customer_id": customer_id,
        "category": category,
        "priority": priority,
        "status": status,
        "agent_id": agent_id,
        "region": region,
        "channel": channel,
        "resolution_hours": resolution_hours_val,
        "sla_met": sla_met if resolved_at else None,
        "satisfaction_score": satisfaction_score,
    }


def main() -> None:
    conn = psycopg2.connect(TARGET_DSN)
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS support_tickets (
                ticket_id          INTEGER PRIMARY KEY,
                created_at         TIMESTAMPTZ NOT NULL,
                resolved_at        TIMESTAMPTZ,
                customer_id        INTEGER NOT NULL,
                category           TEXT NOT NULL,
                priority           TEXT NOT NULL,
                status             TEXT NOT NULL,
                agent_id           TEXT NOT NULL,
                region             TEXT NOT NULL,
                channel            TEXT NOT NULL,
                resolution_hours   NUMERIC(8,2),
                sla_met            BOOLEAN,
                satisfaction_score INTEGER
            )
        """
        )
        conn.commit()
        print("Table 'support_tickets' ready")

        # 3. Clear existing rows and re-seed
        cur.execute("DELETE FROM support_tickets")

        # ~6 tickets per day over 170 days = ~1 020 rows
        tickets = [build_ticket(i) for i in range(1, 1021)]

        cur.executemany(
            """
            INSERT INTO support_tickets (
                ticket_id, created_at, resolved_at, customer_id,
                category, priority, status, agent_id, region, channel,
                resolution_hours, sla_met, satisfaction_score
            ) VALUES (
                %(ticket_id)s, %(created_at)s, %(resolved_at)s, %(customer_id)s,
                %(category)s, %(priority)s, %(status)s, %(agent_id)s, %(region)s,
                %(channel)s, %(resolution_hours)s, %(sla_met)s, %(satisfaction_score)s
            )
            """,
            tickets,
        )
        conn.commit()

    conn.close()
    print(f"Inserted {len(tickets)} support_tickets rows")
    print()
    print("Connect via the app with:")
    print("  host=localhost  port=5432  database=agentic_bi")
    print("  username=user  password=password")


if __name__ == "__main__":
    main()
