"""
Explainability Agent — builds an explainability receipt for each detected insight.

Subscribes to the `insight_detected` Redis stream (the same events the WebSocket
listener tails) and, for every new InsightEvent, computes and persists an
InsightExplanation: confidence score, source dataset, data freshness, KPI formula.
Deterministic — no LLM call.

Run as a standalone worker:  python -m app.agents.explainability_agent
"""

import logging
import uuid

from app.agents.messaging import INSIGHT_DETECTED, AgentEvent, AgentSubscriber
from app.core.database import SessionLocal
from app.models.insight import InsightEvent
from app.services.explainability_service import build_explanation

logger = logging.getLogger(__name__)


class ExplainabilityAgent(AgentSubscriber):
    def __init__(self, consumer_name: str = "explainability-agent-worker-1") -> None:
        super().__init__(
            group_name="explainability-agent",
            consumer_name=consumer_name,
            event_types=[INSIGHT_DETECTED],
        )

    def handle_event(self, event: AgentEvent) -> None:
        insight_id_raw = event.payload.get("id")
        if not insight_id_raw:
            logger.warning("insight_detected event missing id: %s", event.event_id)
            return

        try:
            insight_id = uuid.UUID(str(insight_id_raw))
        except ValueError:
            logger.error("Invalid insight id in event %s: %s", event.event_id, insight_id_raw)
            return

        db = SessionLocal()
        try:
            insight = db.get(InsightEvent, insight_id)
            if insight is None:
                logger.warning("InsightEvent %s not found — skipping explanation", insight_id)
                return
            explanation = build_explanation(db, insight)
            logger.info(
                "Built explanation for insight %s (confidence=%d)",
                insight_id,
                explanation.confidence_score,
            )
        except Exception:
            logger.exception("Explanation build failed for insight %s", insight_id)
            db.rollback()
        finally:
            db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    agent = ExplainabilityAgent()
    logger.info("Explainability Agent started")
    agent.run()
