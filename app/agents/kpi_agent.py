"""
KPI Agent — generates KPI definitions for a dataset using Gemini via ADK.

Triggered two ways:
  1. HTTP: POST /api/v1/datasets/{dataset_id}/kpis/generate
  2. Redis: dataset_quality_passed event (runs as a standalone worker)
"""

import asyncio
import logging
import os
import re
import uuid
from contextlib import nullcontext

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
from app.crud.kpi import create_kpi, list_kpis
from app.crud.schema_metadata import get_schema_metadata_by_table
from app.prompts import load_prompt
from app.schemas.kpi import KPICreate
from app.services.audit_service import SYSTEM_ROLE, record_audit
from app.services.embedding_service import upsert_embedding
from app.services.hitl_workflow_service import create_kpi_approval
from app.services.kpi_calculation_service import snapshot_kpi
from app.services.langfuse_service import get_langfuse

logger = logging.getLogger(__name__)

EVENT_QUALITY_PASSED = "dataset_quality_passed"
EVENT_KPI_GENERATED = "kpi_generated"
EVENT_DATASET_REFRESHED = "dataset_refreshed"
EVENT_KPIS_RECOMPUTED = "kpis_recomputed"


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


async def _ensure_schema_metadata(db: Session, dataset, lookup_name: str):
    """Run schema detection inline when no schema_metadata exists for the table yet.

    KPI generation depends on schema_metadata, but the frontend triggers detection in
    a separate call that can land *after* the on-sync auto-generation. To make
    generation order-independent we detect here from the dataset's schema_fingerprint
    (``{column_name: type}``). Returns the metadata row, or None when there is no
    fingerprint to detect from.
    """
    from app.agents.schema_detection_agent import detect
    from app.schemas.schema_detection import ColumnInput, SchemaDetectRequest

    fingerprint = dataset.schema_fingerprint or {}
    if not fingerprint:
        return None

    logger.info("schema_metadata missing for '%s' — running schema detection inline", lookup_name)
    request = SchemaDetectRequest(
        table_name=lookup_name,
        columns=[
            ColumnInput(name=name, type=str(col_type)) for name, col_type in fingerprint.items()
        ],
    )
    await detect(db, request)
    return get_schema_metadata_by_table(db, lookup_name)


async def generate_kpis_for_dataset(db: Session, dataset_id: uuid.UUID) -> list[uuid.UUID]:
    """Generate KPI definitions for a dataset and return the created KPI IDs."""
    dataset = get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")

    if not settings.GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="LLM not configured: GEMINI_API_KEY is not set")

    os.environ.setdefault("GOOGLE_API_KEY", settings.GEMINI_API_KEY)

    # Extract actual table name from source_query (e.g. "SELECT * FROM support_tickets")
    # Fall back to dataset.name if extraction fails
    table_name_match = re.search(r"\bFROM\s+([^\s;,)]+)", dataset.source_query, re.IGNORECASE)
    lookup_name = table_name_match.group(1) if table_name_match else dataset.name

    schema_meta = get_schema_metadata_by_table(db, lookup_name)
    if schema_meta is None:
        # Auto-generation can fire (on first sync) before the frontend's separate
        # /schema/detect call has populated schema_metadata. Run detection inline so
        # generation is self-sufficient and order-independent.
        schema_meta = await _ensure_schema_metadata(db, dataset, lookup_name)
    if schema_meta is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Schema metadata not found for table '{lookup_name}' and could not be "
                "auto-detected (dataset has no schema fingerprint). Run schema detection first."
            ),
        )

    prompt = _build_prompt(schema_meta)

    lf = get_langfuse()
    trace_cm = (
        lf.start_as_current_observation(
            as_type="trace",
            name="kpi_generation",
            metadata={"dataset_id": str(dataset_id), "table_name": lookup_name},
        )
        if lf
        else nullcontext()
    )

    with trace_cm as lf_trace:
        gen_cm = (
            lf.start_as_current_observation(
                as_type="generation",
                name="gemini_kpi_generation",
                model=settings.GEMINI_LLM_MODEL,
            )
            if lf
            else nullcontext()
        )
        with gen_cm as lf_gen:
            if lf_gen:
                lf_gen.update(input=prompt)

            session = await _session_service.create_session(
                app_name="kpi_generation", user_id="system"
            )
            message = types.Content(role="user", parts=[types.Part(text=prompt)])

            response_text = ""
            async for event in _runner.run_async(
                user_id="system", session_id=session.id, new_message=message
            ):
                if event.is_final_response() and event.content and event.content.parts:
                    response_text = event.content.parts[0].text

            if lf_gen:
                lf_gen.update(output=response_text)

        try:
            llm_output = _KPILLMOutput.model_validate_json(response_text)
        except Exception as err:
            if lf_trace:
                lf_trace.update(
                    level="ERROR", status_message="LLM returned unparseable KPI response"
                )
            raise HTTPException(
                status_code=502, detail="LLM returned an unparseable KPI response"
            ) from err

        kpi_ids: list[uuid.UUID] = []
        for raw in llm_output.kpis:
            kpi_create = KPICreate(
                dataset_id=dataset_id,
                table_name=lookup_name,
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

            record_audit(
                db,
                action="kpi.created",
                entity_type="kpi",
                entity_id=kpi.id,
                actor_role=SYSTEM_ROLE,
                summary=f"KPI '{kpi.name}' auto-generated for dataset {dataset_id}",
                details={"dataset_id": str(dataset_id), "source": "kpi_agent"},
            )

            try:
                create_kpi_approval(db, kpi.id)
            except Exception:
                logger.warning(
                    "Approval request creation failed for KPI %s — continuing",
                    kpi.id,
                    exc_info=True,
                )

            try:
                snapshot_kpi(db, kpi)
            except Exception:
                logger.warning(
                    "Snapshot failed for KPI %s (%s) — continuing", kpi.id, kpi.name, exc_info=True
                )
                db.rollback()

            embed_text = (
                f"KPI: {kpi.display_name}\n"
                f"Description: {kpi.description}\n"
                f"Category: {kpi.category}\n"
                f"Formula: {kpi.formula}\n"
                f"Direction: {kpi.direction}"
            )
            try:
                upsert_embedding(db, "kpi_definition", str(kpi.id), embed_text)
            except Exception:
                # An embedding failure must not abort the whole batch — the KPI is
                # already committed; pgvector lookup is a best-effort enhancement.
                logger.warning(
                    "Embedding failed for KPI %s (%s) — continuing",
                    kpi.id,
                    kpi.name,
                    exc_info=True,
                )
                db.rollback()

            kpi_ids.append(kpi.id)

        if lf_trace:
            lf_trace.update(
                output={"kpi_count": len(kpi_ids), "kpi_ids": [str(k) for k in kpi_ids]}
            )

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


def recompute_kpis_for_dataset(db: Session, dataset_id: uuid.UUID) -> list[uuid.UUID]:
    """Recompute snapshots for all certified KPIs of a dataset.

    Called on dataset refresh — does not regenerate KPI definitions.
    """
    kpis = list_kpis(db, dataset_id=dataset_id, status="certified")
    recomputed: list[uuid.UUID] = []
    for kpi in kpis:
        try:
            snapshot_kpi(db, kpi)
            recomputed.append(kpi.id)
        except Exception:
            logger.warning("Snapshot recompute failed for KPI %s — skipping", kpi.id, exc_info=True)
            db.rollback()
    logger.info("Recomputed %d KPI snapshots for dataset %s", len(recomputed), dataset_id)
    return recomputed


class KPIAgent(AgentSubscriber):
    def __init__(self, consumer_name: str = "kpi-agent-worker-1") -> None:
        super().__init__(
            group_name="kpi-agent",
            consumer_name=consumer_name,
            event_types=[EVENT_QUALITY_PASSED, EVENT_DATASET_REFRESHED],
        )
        self._publisher = AgentPublisher(self._redis)

    def handle_event(self, event: AgentEvent) -> None:
        if event.event_type == EVENT_DATASET_REFRESHED:
            self._handle_dataset_refreshed(event)
        else:
            self._handle_quality_passed(event)

    def _handle_quality_passed(self, event: AgentEvent) -> None:
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

    def _handle_dataset_refreshed(self, event: AgentEvent) -> None:
        dataset_id_raw = event.payload.get("dataset_id")
        if not dataset_id_raw:
            logger.warning("dataset_refreshed event missing dataset_id: %s", event.event_id)
            return

        try:
            dataset_id = uuid.UUID(str(dataset_id_raw))
        except ValueError:
            logger.error("Invalid dataset_id in event %s: %s", event.event_id, dataset_id_raw)
            return

        logger.info("Recomputing KPI snapshots for refreshed dataset %s", dataset_id)

        db = SessionLocal()
        try:
            kpi_ids = recompute_kpis_for_dataset(db, dataset_id)
        except Exception:
            logger.exception("KPI recompute failed for dataset %s", dataset_id)
            return
        finally:
            db.close()

        self._publisher.publish(
            EVENT_KPIS_RECOMPUTED,
            {
                "dataset_id": str(dataset_id),
                "kpi_ids": [str(k) for k in kpi_ids],
                "count": len(kpi_ids),
            },
        )
        logger.info("Published kpis_recomputed for dataset %s (%d KPIs)", dataset_id, len(kpi_ids))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    agent = KPIAgent()
    logger.info("KPI Agent started")
    agent.run()
