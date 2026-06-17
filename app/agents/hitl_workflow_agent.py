"""
HITL Workflow Agent — pure orchestration, no LLM calls.

Subscribes to kpi_generated events. For each KPI, creates an ApprovalRequest
at the analyst_review stage, then publishes kpi_pending_review so downstream
agents (Insight, Reporting, etc.) know the batch is queued for review.

SLA breach detection: subscribe to approval_overdue events published by the
router's GET /approvals?overdue=true endpoint (or add a scheduled check here).
"""

import logging
import uuid

from app.agents.messaging import AgentEvent, AgentPublisher, AgentSubscriber
from app.core.database import SessionLocal
from app.services.hitl_workflow_service import create_kpi_approval

logger = logging.getLogger(__name__)

EVENT_KPI_GENERATED = "kpi_generated"
EVENT_KPI_PENDING_REVIEW = "kpi_pending_review"


def generate_kpi_approvals(db, kpi_ids: list[uuid.UUID]) -> list:
    """Create ApprovalRequests for a batch of KPI IDs. Returns the created ARs."""
    ars = []
    for kpi_id in kpi_ids:
        ar = create_kpi_approval(db, kpi_id)
        ars.append(ar)
    return ars


class HITLWorkflowAgent(AgentSubscriber):
    def __init__(self, consumer_name: str = "hitl-agent-worker-1") -> None:
        super().__init__(
            group_name="hitl-agent",
            consumer_name=consumer_name,
            event_types=[EVENT_KPI_GENERATED],
        )
        self._publisher = AgentPublisher(self._redis)

    def handle_event(self, event: AgentEvent) -> None:
        kpi_ids_raw = event.payload.get("kpi_ids", [])
        dataset_id = event.payload.get("dataset_id")

        try:
            kpi_ids = [uuid.UUID(str(k)) for k in kpi_ids_raw]
        except ValueError:
            logger.error("Invalid kpi_ids in event %s", event.event_id)
            return

        if not kpi_ids:
            logger.warning("kpi_generated event %s has no kpi_ids", event.event_id)
            return

        logger.info("Creating approval requests for %d KPIs (dataset=%s)", len(kpi_ids), dataset_id)

        db = SessionLocal()
        try:
            ars = generate_kpi_approvals(db, kpi_ids)
        except Exception:
            logger.exception("Failed to create approval requests for event %s", event.event_id)
            return
        finally:
            db.close()

        self._publisher.publish(
            EVENT_KPI_PENDING_REVIEW,
            {
                "dataset_id": dataset_id,
                "kpi_ids": [str(k) for k in kpi_ids],
                "approval_request_ids": [str(ar.id) for ar in ars],
            },
        )
        logger.info(
            "Published kpi_pending_review for %d KPIs (dataset=%s)", len(kpi_ids), dataset_id
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    agent = HITLWorkflowAgent()
    logger.info("HITL Workflow Agent started")
    agent.run()
