import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import sqlalchemy

from app.core.database import SessionLocal

db = SessionLocal()
try:
    result = db.execute(
        sqlalchemy.text("SELECT status, COUNT(*) FROM kpi_definitions GROUP BY status")
    )
    rows = result.fetchall()
    print("KPI statuses in Supabase:")
    for r in rows:
        print(f"  {r[0]}: {r[1]}")
finally:
    db.close()
