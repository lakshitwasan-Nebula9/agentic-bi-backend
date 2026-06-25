import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.routers import (
    approvals,
    auth,
    connectors,
    dashboards,
    data_quality,
    datasets,
    health,
    insights,
    kpis,
    rag,
    reports,
    schema,
    users,
)
from app.ws.insight_listener import run_insight_listener

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run the insight WebSocket listener for the lifetime of the app."""
    listener = asyncio.create_task(run_insight_listener())
    try:
        yield
    finally:
        listener.cancel()
        try:
            await listener
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(approvals.router, prefix=settings.API_V1_PREFIX)
app.include_router(health.router, prefix=settings.API_V1_PREFIX)
app.include_router(insights.router, prefix=settings.API_V1_PREFIX)
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(connectors.router, prefix=settings.API_V1_PREFIX)
app.include_router(dashboards.router, prefix=settings.API_V1_PREFIX)
app.include_router(datasets.router, prefix=settings.API_V1_PREFIX)
app.include_router(data_quality.router, prefix=settings.API_V1_PREFIX)
app.include_router(rag.router, prefix=settings.API_V1_PREFIX)
app.include_router(schema.router, prefix=settings.API_V1_PREFIX)
app.include_router(users.router, prefix=settings.API_V1_PREFIX)
app.include_router(kpis.router, prefix=settings.API_V1_PREFIX)
app.include_router(reports.router, prefix=settings.API_V1_PREFIX)


@app.get("/")
def root():
    return {"message": f"Welcome to {settings.APP_NAME}"}
