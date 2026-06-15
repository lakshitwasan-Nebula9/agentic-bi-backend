import json
import os

from fastapi import HTTPException
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.prompts import load_prompt
from app.schemas.schema_detection import (
    ColumnAnnotation,
    SchemaDetectRequest,
    SchemaDetectResponse,
)
from app.services.embedding_service import upsert_embedding


class _SchemaLLMOutput(BaseModel):
    entity_type: str
    description: str
    columns: list[ColumnAnnotation]
    identifiers: list[str]
    dimensions: list[str]
    measures: list[str]
    date_columns: list[str]

    suggested_kpis: list[str]
    business_questions: list[str]


_prompt = load_prompt("schema_detection")

_session_service: InMemorySessionService = InMemorySessionService()
_agent: Agent = Agent(
    name="schema_detection_agent",
    model=settings.GEMINI_LLM_MODEL,
    instruction=_prompt["instruction"],
    output_schema=_SchemaLLMOutput,
)
_runner: Runner = Runner(
    agent=_agent,
    app_name="schema_detection",
    session_service=_session_service,
)


async def detect(db: Session, request: SchemaDetectRequest) -> SchemaDetectResponse:
    if not settings.GEMINI_API_KEY:
        raise HTTPException(
            status_code=503, detail="LLM not configured: GEMINI_API_KEY is not set"
        )

    os.environ.setdefault("GOOGLE_API_KEY", settings.GEMINI_API_KEY)

    prompt = f"""
    Analyze the following database table.

    Table Name:
    {request.table_name}

    Columns:
    {json.dumps([c.model_dump() for c in request.columns], indent=2)}

    Requirements:

    1. Determine the business entity represented by this table.
    2. Generate a concise business description.
    3. Annotate every column with:
    - label
    - business_definition
    - role

    Valid roles:
    - identifier
    - dimension
    - measure
    - date

    4. Identify:
    - identifiers
    - dimensions
    - measures
    - date_columns

    5. Suggest KPIs that can be calculated directly from this table.
    6. Suggest realistic business questions answerable from this table.
    7. Do not invent relationships with other tables.
    8. Do not suggest KPIs unsupported by the schema.
    9. Return ONLY valid JSON.
    """

    session = await _session_service.create_session(
        app_name="schema_detection", user_id="system"
    )
    message = types.Content(role="user", parts=[types.Part(text=prompt)])

    response_text = ""
    async for event in _runner.run_async(
        user_id="system", session_id=session.id, new_message=message
    ):
        if event.is_final_response() and event.content and event.content.parts:
            response_text = event.content.parts[0].text
            break

    try:
        result = _SchemaLLMOutput.model_validate_json(response_text)
    except Exception as err:
        raise HTTPException(
            status_code=502, detail="LLM returned an unparseable response"
        ) from err

    embed_content = f"""
        Table Name:
        {request.table_name}

        Entity Type:
        {result.entity_type}

        Description:
        {result.description}

        Identifiers:
        {' '.join(result.identifiers)}

        Dimensions:
        {' '.join(result.dimensions)}

        Measures:
        {' '.join(result.measures)}

        Date Columns:
        {' '.join(result.date_columns)}

        KPIs:
        {' '.join(result.suggested_kpis)}

        Business Questions:
        {' '.join(result.business_questions)}

        Column Definitions:
        {' '.join(c.business_definition for c in result.columns)}
        """
    record = upsert_embedding(db, "schema_description", request.table_name, embed_content)

    return SchemaDetectResponse(
        table_name=request.table_name,
        entity_type=result.entity_type,
        description=result.description,
        columns=result.columns,
        identifiers=result.identifiers,
        dimensions=result.dimensions,
        measures=result.measures,
        date_columns=result.date_columns,
        suggested_kpis=result.suggested_kpis,
        business_questions=result.business_questions,
        embedding_id=record.id,
    )
