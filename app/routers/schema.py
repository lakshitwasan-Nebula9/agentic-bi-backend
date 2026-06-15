from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agents import schema_detection_agent
from app.core.database import get_db
from app.schemas.schema_detection import SchemaDetectRequest, SchemaDetectResponse

router = APIRouter(prefix="/schema", tags=["schema"])


@router.post("/detect", response_model=SchemaDetectResponse, status_code=201)
async def detect_schema(payload: SchemaDetectRequest, db: Session = Depends(get_db)):
    return await schema_detection_agent.detect(db, payload)
