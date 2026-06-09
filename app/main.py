from fastapi import FastAPI

from app.core.config import settings
from app.routers import health

app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG,
)

app.include_router(health.router, prefix=settings.API_V1_PREFIX)


@app.get("/")
def root():
    return {"message": f"Welcome to {settings.APP_NAME}"}
