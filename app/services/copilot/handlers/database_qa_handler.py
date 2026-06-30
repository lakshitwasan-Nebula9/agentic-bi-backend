"""
Database Q&A handler — Text-to-SQL against the user's connected data source.

Flow:
  1. Resolve which connector/dataset to query
     - Prefer dataset linked to visible KPIs on current dashboard
     - Fall back to the first active connector
  2. Load SchemaMetadata for that dataset (structured, no vector search)
  3. Gemini generates SQL from schema + question
  4. Validate SQL (block write operations)
  5. Execute via psycopg2 directly on the connector
  6. Gemini formats result as natural language
"""

import logging
import re

import psycopg2
import psycopg2.extras
from sqlalchemy.orm import Session

from app.models.connector import DataConnector
from app.models.dataset import Dataset
from app.models.kpi import KPIDefinition
from app.models.schema_metadata import SchemaMetadata
from app.models.user import User
from app.schemas.copilot import ScreenContext, SourceReference, SuggestedAction
from app.services.connector_service import get_decrypted_password
from app.services.copilot.gemini_client import generate_text
from app.services.copilot.handlers.base_handler import BaseHandler, HandlerResult

logger = logging.getLogger(__name__)

_WRITE_OPS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|EXEC|EXECUTE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

_SQL_GEN_SYSTEM = """You are a SQL expert for an enterprise BI platform.
Generate a single, read-only SQL SELECT query to answer the user's question.
Rules:
- Output ONLY the SQL — no explanation, no markdown, no code fences.
- Use only the tables and columns described in the schema below.
- Add LIMIT 500 to all queries.
- Never use INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE.
- Use standard PostgreSQL syntax."""

_NARRATE_SYSTEM = """You are a business analyst assistant.
Convert SQL query results into a concise natural language summary (3–5 sentences).
Focus on the business meaning. Use plain English. Round numbers to 2 decimal places.
If the result set is empty, say so clearly."""


def _build_schema_prompt(schema: SchemaMetadata) -> str:
    lines = [f"Table: {schema.table_name}", f"Description: {schema.description}"]
    if schema.columns and isinstance(schema.columns, list):
        lines.append("Columns:")
        for col in schema.columns:
            if isinstance(col, dict):
                name = col.get("name", "")
                label = col.get("label", name)
                role = col.get("role", "")
                defn = col.get("business_definition", "")
                lines.append(f"  - {name} ({role}): {label}. {defn}")
    if schema.date_columns:
        dc = schema.date_columns
        if isinstance(dc, list):
            lines.append(f"Date columns: {', '.join(dc)}")
    return "\n".join(lines)


def _active_connector_q(db: Session, user_id):
    """Base query: connectors owned by this user that are not soft-deleted."""
    return db.query(DataConnector).filter(
        DataConnector.created_by == user_id,
        DataConnector.is_active.is_(True),
        DataConnector.is_deleted.is_(False),
    )


def _resolve_connector(
    db: Session,
    screen_context: ScreenContext | None,
    user_id=None,
) -> tuple[DataConnector | None, Dataset | None, SchemaMetadata | None]:
    """Find the best connector + dataset + schema to answer the user's question."""
    dataset: Dataset | None = None
    connector: DataConnector | None = None
    schema: SchemaMetadata | None = None

    # Try: KPIs visible on dashboard → their datasets → connector owned by this user
    if screen_context and screen_context.visible_kpi_ids:
        kpis = (
            db.query(KPIDefinition)
            .filter(KPIDefinition.id.in_(screen_context.visible_kpi_ids))
            .limit(1)
            .all()
        )
        if kpis:
            dataset = db.get(Dataset, kpis[0].dataset_id)
            if dataset:
                schema = (
                    db.query(SchemaMetadata).filter(SchemaMetadata.dataset_id == dataset.id).first()
                )
                connector = db.get(DataConnector, dataset.connector_id)
                # Reject if connector belongs to a different user
                if connector and user_id and str(connector.created_by) != str(user_id):
                    connector = None

    # Fall back to the user's first active connector
    if connector is None:
        q = _active_connector_q(db, user_id) if user_id else db.query(DataConnector)
        connector = q.order_by(DataConnector.created_at.asc()).first()
        if connector:
            dataset = db.query(Dataset).filter(Dataset.connector_id == connector.id).first()
            if dataset:
                schema = (
                    db.query(SchemaMetadata).filter(SchemaMetadata.dataset_id == dataset.id).first()
                )

    return connector, dataset, schema


def _run_query(connector: DataConnector, sql: str) -> tuple[list[str], list[tuple]]:
    """Execute SQL on the connector's source database. Returns (columns, rows)."""
    password = get_decrypted_password(connector)
    conn = psycopg2.connect(
        host=connector.host,
        port=connector.port,
        dbname=connector.database_name,
        user=connector.username,
        password=password,
        connect_timeout=10,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = cur.fetchmany(500)
            return columns, rows
    finally:
        conn.close()


def _format_results(columns: list[str], rows: list[tuple], limit: int = 20) -> str:
    if not rows:
        return "The query returned no results."
    header = " | ".join(columns)
    sep = "-" * len(header)
    lines = [header, sep]
    for row in rows[:limit]:
        lines.append(" | ".join(str(v) if v is not None else "NULL" for v in row))
    if len(rows) > limit:
        lines.append(f"... and {len(rows) - limit} more rows")
    return "\n".join(lines)


class DatabaseQAHandler(BaseHandler):
    async def handle(
        self,
        message: str,
        screen_context: ScreenContext | None,
        history: list[dict],
        current_user: User,
        db: Session,
    ) -> HandlerResult:
        connector, dataset, schema = _resolve_connector(db, screen_context, user_id=current_user.id)

        if connector is None:
            return HandlerResult(
                response="I couldn't find a connected data source to query. Please set up a connector first.",
                suggested_actions=[SuggestedAction(label="Add Connector", route="/connectors")],
            )

        schema_text = (
            _build_schema_prompt(schema)
            if schema
            else f"Table: {dataset.name if dataset else 'unknown'} (no schema metadata available)"
        )

        sql_prompt = f"""Schema:
{schema_text}

User question: {message}

Write a SQL SELECT query to answer this question."""

        sql = await generate_text(sql_prompt, system_instruction=_SQL_GEN_SYSTEM)

        if not sql:
            return HandlerResult(
                response="I wasn't able to generate a SQL query for your question. Could you rephrase it?"
            )

        # Strip markdown fences if LLM added them
        sql = sql.strip()
        if sql.startswith("```"):
            lines = sql.splitlines()
            sql = "\n".join(lines[1:-1]).strip()

        # Safety check — block write operations
        if _WRITE_OPS.search(sql):
            return HandlerResult(
                response="I can only run read-only queries. The generated query contained a write operation and was blocked."
            )

        try:
            columns, rows = _run_query(connector, sql)
        except Exception as exc:
            logger.warning("SQL execution failed: %s — sql=%r", exc, sql[:300])
            return HandlerResult(
                response=f"The query ran into an error: {exc}. You can try rephrasing your question.",
                sql_generated=sql,
            )

        results_text = _format_results(columns, rows)

        narrate_prompt = f"""Question: {message}

SQL used:
{sql}

Query results:
{results_text}

Summarise these results in plain English for a business user."""

        narrative = await generate_text(narrate_prompt, system_instruction=_NARRATE_SYSTEM)
        response = narrative or f"Query returned {len(rows)} row(s):\n\n{results_text}"

        refs = [
            SourceReference(
                type="connector",
                id=str(connector.id),
                name=connector.name,
                route=f"/connectors/{connector.id}",
            )
        ]
        if dataset:
            refs.append(
                SourceReference(
                    type="dataset",
                    id=str(dataset.id),
                    name=dataset.name,
                    route=f"/datasets/{dataset.id}",
                )
            )

        return HandlerResult(
            response=response,
            sql_generated=sql,
            source_references=refs,
        )
