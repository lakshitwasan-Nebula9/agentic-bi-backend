"""
Data Quality Agent — subscribes to `dataset_synced` events and runs the
4-layer quality pipeline. Publishes `dataset_quality_passed` or
`dataset_quarantined` downstream so the KPI pipeline knows what to process.

Run this as a standalone worker:
    python -m app.agents.data_quality_agent
"""

import logging
import uuid

from app.agents.messaging import AgentEvent, AgentPublisher, AgentSubscriber
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)

EVENT_DATASET_SYNCED = "dataset_synced"
EVENT_QUALITY_PASSED = "dataset_quality_passed"
EVENT_QUARANTINED = "dataset_quarantined"


class DataQualityAgent(AgentSubscriber):
    def __init__(self, consumer_name: str = "data-quality-worker-1") -> None:
        super().__init__(
            group_name="data-quality-agent",
            consumer_name=consumer_name,
            event_types=[EVENT_DATASET_SYNCED],
        )
        self._publisher = AgentPublisher(self._redis)

    def handle_event(self, event: AgentEvent) -> None:
        from app.services.data_quality_service import run_quality_pipeline

        dataset_id_raw = event.payload.get("dataset_id")
        if not dataset_id_raw:
            logger.warning("dataset_synced event missing dataset_id: %s", event.event_id)
            return

        try:
            dataset_id = uuid.UUID(str(dataset_id_raw))
        except ValueError:
            logger.error("Invalid dataset_id in event %s: %s", event.event_id, dataset_id_raw)
            return

        logger.info("Running quality pipeline for dataset %s", dataset_id)

        db = SessionLocal()
        try:
            scorecard = run_quality_pipeline(db, dataset_id)
        except Exception:
            logger.exception("Quality pipeline failed for dataset %s", dataset_id)
            return
        finally:
            db.close()

        result_event = EVENT_QUARANTINED if scorecard.should_quarantine else EVENT_QUALITY_PASSED
        self._publisher.publish(
            result_event,
            {
                "dataset_id": str(dataset_id),
                "quality_score": scorecard.overall_score,
                "status_label": scorecard.status_label,
            },
        )

        logger.info(
            "Dataset %s quality check complete: score=%.1f status=%s",
            dataset_id,
            scorecard.overall_score,
            scorecard.status_label,
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    agent = DataQualityAgent()
    logger.info("Data Quality Agent started")
    agent.run()
