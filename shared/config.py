from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    All configuration values are read from the .env file automatically.

    Why pydantic-settings?
    - Type-safe: if DATABASE_URL is missing, startup fails with a clear error.
    - No manual os.environ.get() calls scattered through the codebase.
    - The lru_cache below ensures we only read the file once.

    Production secret key requirements
    -----------------------------------
    SECRET_KEY must be a randomly generated string of at least 32 characters.
    The application refuses to start in production if SECRET_KEY is default,
    empty, or insufficiently short.
    See shared.auth.jwt.validate_secret_key_for_environment().

    On Render, SECRET_KEY is auto-generated via generateValue: true in render.yaml.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # silently ignore unknown env vars
    )

    # ── Database ──────────────────────────────────────────────────────────
    database_url: str

    @property
    def async_database_url(self) -> str:
        """Convert standard postgres:// URL to asyncpg format for SQLAlchemy."""
        url = self.database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    # ── Redis ─────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── Security ──────────────────────────────────────────────────────────
    secret_key: str = "dev-secret-change-in-production"
    access_token_expire_minutes: int = 60
    algorithm: str = "HS256"

    # ── Twilio ────────────────────────────────────────────────────────────
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""
    twilio_sms_from: str = ""

    # ── SendGrid ──────────────────────────────────────────────────────────
    sendgrid_api_key: str = ""
    email_from: str = ""

    # ── LLM ───────────────────────────────────────────────────────────────
    groq_api_key: str = ""
    openai_api_key: str = ""
    llm_model: str = "llama-3.1-8b-instant"
    llm_max_tokens: int = 1000
    copilot_provider: str = "deterministic"
    copilot_max_retries: int = 1
    copilot_checkpoint_backend: str = "postgres"
    copilot_checkpoint_retention_days: int = 30

    # ── App ───────────────────────────────────────────────────────────────
    app_env: str = "development"
    app_port: int = 8000
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached Settings instance.
    Call get_settings() anywhere — it reads the .env file only once.
    """
    return Settings()


# Convenience singleton used throughout the app
settings = get_settings()
