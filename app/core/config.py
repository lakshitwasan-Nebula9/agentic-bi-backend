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

    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:3000",
    ]

    CONNECTOR_ENCRYPTION_KEY: str = "nXVAMA1WlKWTqw6YCIpBHXGt09CZhrJyUHssyc68ebU="

    DATA_QUALITY_THRESHOLD: float = 60.0

    GEMINI_API_KEY: str | None = None
    GEMINI_LLM_MODEL: str = "gemini-2.0-flash"

    ANTHROPIC_API_KEY: str | None = None
    COPILOT_LLM_MODEL: str = "claude-haiku-4-5-20251001"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIMENSIONS: int = 384

    HITL_SLA_ANALYST_HOURS: int = 24
    HITL_SLA_BUSINESS_OWNER_HOURS: int = 48
    HITL_SLA_CERTIFICATION_HOURS: int = 72

    LANGFUSE_SECRET_KEY: str | None = None
    LANGFUSE_PUBLIC_KEY: str | None = None
    LANGFUSE_BASE_URL: str = "https://cloud.langfuse.com"

    # Decision Agent — SLA hours per priority
    DECISION_SLA_HOURS_P1: int = 24
    DECISION_SLA_HOURS_P2: int = 48
    DECISION_SLA_HOURS_P3: int = 72

    # Decision Agent — priority rule thresholds
    DECISION_ADVERSE_SLOPE_THRESHOLD: float = 5.0

    # Decision Agent — owner role routing
    DECISION_P1_OWNER_OVERRIDE: str = "executive"
    DECISION_DEFAULT_OWNER_ROLE: str = "analyst"
    DECISION_CATEGORY_OWNER_MAP: dict[str, str] = {
        "revenue": "executive",
        "sales": "manager",
        "financial": "manager",
        "finance": "manager",
        "operational": "operations",
        "operations": "operations",
        "customer": "manager",
        "inventory": "operations",
        "marketing": "manager",
        "strategic": "executive",
        "data_quality": "analyst",
    }


settings = Settings()
