from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "Agentic BI"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    DATABASE_URL: str = "postgresql://user:password@localhost:5432/agentic_bi"

    class Config:
        env_file = ".env"


settings = Settings()
