from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
    APP_NAME: str = "Agentic BI"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    DATABASE_URL: str = "postgresql://user:password@localhost:5432/agentic_bi"
    REDIS_URL: str = "redis://localhost:6379/0"

    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    GOOGLE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_OAUTH_ALLOWED_DOMAIN: str | None = None

    CONNECTOR_ENCRYPTION_KEY: str = "nXVAMA1WlKWTqw6YCIpBHXGt09CZhrJyUHssyc68ebU="

    DATA_QUALITY_THRESHOLD: float = 60.0

    GEMINI_API_KEY: str | None = None
    GEMINI_LLM_MODEL: str = "gemini-2.0-flash"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIMENSIONS: int = 384


settings = Settings()
