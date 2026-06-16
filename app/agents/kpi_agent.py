"""
KPI Agent — generates KPI definitions for a dataset using Gemini via ADK.

Triggered two ways:
  1. HTTP: POST /api/v1/datasets/{dataset_id}/kpis/generate
  2. Redis: dataset_quality_passed event (runs as a standalone worker)
"""

import asyncio
import logging
import os
import uuid

from fastapi import HTTPException
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.messaging import AgentEvent, AgentPublisher, AgentSubscriber
from app.core.config import settings
from app.core.database import SessionLocal
from app.crud.dataset import get_dataset
from app.crud.kpi import create_kpi
from app.crud.schema_metadata import get_schema_metadata_by_table
from app.prompts import load_prompt
from app.schemas.kpi import KPICreate
from app.services.embedding_service import upsert_embedding
from app.services.kpi_calculation_service import compute_and_snapshot

logger = logging.getLogger(__name__)

EVENT_QUALITY_PASSED = "dataset_quality_passed"
EVENT_KPI_GENERATED = "kpi_generated"


class _SingleKPI(BaseModel):
    name: str
    display_name: str
    description: str
    category: str
    formula: str
    sql_expression: str
    unit: str | None = None
    direction: str
    suggested_chart_type: str | None = None


class _KPILLMOutput(BaseModel):
    kpis: list[_SingleKPI]


_prompt = load_prompt("kpi_generation")

_session_service: InMemorySessionService = InMemorySessionService()
_agent: Agent = Agent(
    name="kpi_agent",
    model=settings.GEMINI_LLM_MODEL,
    instruction=_prompt["instruction"],
    output_schema=_KPILLMOutput,
)
_runner: Runner = Runner(
    agent=_agent,
    app_name="kpi_generation",
    session_service=_session_service,
)


async def generate_kpis_for_dataset(db: Session, dataset_id: uuid.UUID) -> list[uuid.UUID]:
    """Generate KPI definitions for a dataset and return the created KPI IDs."""
    dataset = get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")

    if not settings.GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="LLM not configured: GEMINI_API_KEY is not set")

    os.environ.setdefault("GOOGLE_API_KEY", settings.GEMINI_API_KEY)

    schema_meta = get_schema_metadata_by_table(db, dataset.name)
    if schema_meta is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Schema metadata not found for table '{dataset.name}'. "
                "Run schema detection first."
            ),
        )

    prompt = _build_prompt(schema_meta)

    session = await _session_service.create_session(app_name="kpi_generation", user_id="system")
    message = types.Content(role="user", parts=[types.Part(text=prompt)])

    response_text = ""
    async for event in _runner.run_async(
        user_id="system", session_id=session.id, new_message=message
    ):
        if event.is_final_response() and event.content and event.content.parts:
            response_text = event.content.parts[0].text

    try:
        llm_output = _KPILLMOutput.model_validate_json(response_text)
    except Exception as err:
        raise HTTPException(
            status_code=502, detail="LLM returned an unparseable KPI response"
        ) from err

    kpi_ids: list[uuid.UUID] = []
    for raw in llm_output.kpis:
        kpi_create = KPICreate(
            dataset_id=dataset_id,
            table_name=dataset.name,
            name=raw.name,
            display_name=raw.display_name,
            description=raw.description,
            category=raw.category,
            formula=raw.formula,
            sql_expression=raw.sql_expression,
            unit=raw.unit,
            direction=raw.direction,
            suggested_chart_type=raw.suggested_chart_type,
        )
        kpi = create_kpi(db, kpi_create)

        try:
            compute_and_snapshot(db, kpi)
        except Exception:
            logger.warning(
                "Snapshot failed for KPI %s (%s) — continuing", kpi.id, kpi.name, exc_info=True
            )

        embed_text = (
            f"KPI: {kpi.display_name}\n"
            f"Description: {kpi.description}\n"
            f"Category: {kpi.category}\n"
            f"Formula: {kpi.formula}\n"
            f"Direction: {kpi.direction}"
        )
        upsert_embedding(db, "kpi_definition", str(kpi.id), embed_text)

        kpi_ids.append(kpi.id)

    logger.info("Generated %d KPIs for dataset %s", len(kpi_ids), dataset_id)
    return kpi_ids


def _build_prompt(schema_meta) -> str:
    columns_text = ""
    if schema_meta.columns:
        for col in schema_meta.columns:
            if isinstance(col, dict):
                columns_text += (
                    f"  - {col.get('name')} ({col.get('role', 'unknown')}): "
                    f"{col.get('business_definition', '')}\n"
                )

    return f"""
Analyze the following database table schema and generate KPI definitions.

Table: {schema_meta.table_name}
Entity Type: {schema_meta.entity_type}
Description: {schema_meta.description}

Columns:
{columns_text}
Identifiers: {', '.join(schema_meta.identifiers or [])}
Dimensions: {', '.join(schema_meta.dimensions or [])}
Measures: {', '.join(schema_meta.measures or [])}
Date Columns: {', '.join(schema_meta.date_columns or [])}

Suggested KPIs (for reference): {', '.join(schema_meta.suggested_kpis or [])}

Generate 3–6 high-quality KPI definitions. Return ONLY valid JSON.
""".strip()


class KPIAgent(AgentSubscriber):
    def __init__(self, consumer_name: str = "kpi-agent-worker-1") -> None:
        super().__init__(
            group_name="kpi-agent",
            consumer_name=consumer_name,
            event_types=[EVENT_QUALITY_PASSED],
        )
        self._publisher = AgentPublisher(self._redis)

    def handle_event(self, event: AgentEvent) -> None:
        dataset_id_raw = event.payload.get("dataset_id")
        if not dataset_id_raw:
            logger.warning("dataset_quality_passed event missing dataset_id: %s", event.event_id)
            return

        try:
            dataset_id = uuid.UUID(str(dataset_id_raw))
        except ValueError:
            logger.error("Invalid dataset_id in event %s: %s", event.event_id, dataset_id_raw)
            return

        logger.info("Generating KPIs for dataset %s", dataset_id)

        db = SessionLocal()
        try:
            kpi_ids = asyncio.run(generate_kpis_for_dataset(db, dataset_id))
        except Exception:
            logger.exception("KPI generation failed for dataset %s", dataset_id)
            return
        finally:
            db.close()

        self._publisher.publish(
            EVENT_KPI_GENERATED,
            {
                "dataset_id": str(dataset_id),
                "kpi_ids": [str(k) for k in kpi_ids],
                "count": len(kpi_ids),
            },
        )
        logger.info("Published kpi_generated for dataset %s (%d KPIs)", dataset_id, len(kpi_ids))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    agent = KPIAgent()
    logger.info("KPI Agent started")
    agent.run()
