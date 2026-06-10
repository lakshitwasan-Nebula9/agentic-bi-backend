from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health_check():
    return {"status": "ok"}


@router.get("/db")
def health_check_db(db: Session = Depends(get_db)):
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS health_check "
            "(id SERIAL PRIMARY KEY, checked_at TIMESTAMPTZ DEFAULT now())"
        )
    )
    db.execute(text("INSERT INTO health_check DEFAULT VALUES"))
    db.commit()

    row = db.execute(
        text("SELECT id, checked_at FROM health_check ORDER BY id DESC LIMIT 1")
    ).fetchone()

    return {
        "status": "ok",
        "read": True,
        "write": True,
        "last_check": {"id": row.id, "checked_at": row.checked_at},
    }
