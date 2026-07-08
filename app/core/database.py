from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    # Supabase's session-mode pooler caps ALL clients combined at 15 connections.
    # SQLAlchemy's defaults (pool_size=5, max_overflow=10) let this app alone
    # claim all 15, starving every other client (other devs, migration scripts,
    # CI). Keep this app's ceiling well under the shared budget — sizes are
    # env-configurable but default low (see Settings.DB_POOL_SIZE / MAX_OVERFLOW).
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
