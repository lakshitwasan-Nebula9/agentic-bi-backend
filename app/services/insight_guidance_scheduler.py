"""Scheduler for the insight feedback learning loop.

Kept separate from app.services.report_scheduler (Reporting Agent) since the
two are owned by different sprint items — this one turns feedback into Insight
Agent prompt guidance, on its own weekly cadence.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.database import SessionLocal
from app.services.insight_guidance_service import generate_guidance

logger = logging.getLogger(__name__)


async def _run_guidance_job() -> None:
    logger.info("Insight guidance generation job started")
    db = SessionLocal()
    try:
        result = await generate_guidance(db)
        if result is not None:
            logger.info("Insight guidance updated: %s", result.id)
    except Exception:
        logger.exception("Insight guidance generation job failed")
    finally:
        db.close()


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    # Weekly: every Sunday at 06:00 UTC — ahead of the Monday reporting job.
    scheduler.add_job(_run_guidance_job, "cron", day_of_week="sun", hour=6, minute=0)
    return scheduler
