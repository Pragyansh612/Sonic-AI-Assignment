"""Application settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root: .../Sonic-AI-Intern-Assignment (backend/app/config.py -> parents[2])
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"

# Tokens that must never be used when ENV=production.
INSECURE_ADMIN_TOKENS = frozenset(
    {
        "",
        "dev-admin-token",
        "test-admin-token",
        "change-me-to-a-long-random-string",
        "change-me",
        "admin",
        "secret",
        "password",
    }
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    env: str = Field(default="development", alias="ENV")
    mongodb_uri: str = Field(default="mongodb://localhost:27017", alias="MONGODB_URI")
    mongodb_db: str = Field(default="acmecorp", alias="MONGODB_DB")
    admin_api_token: str = Field(default="dev-admin-token", alias="ADMIN_API_TOKEN")
    frontend_origin: str = Field(default="http://localhost:3000", alias="FRONTEND_ORIGIN")
    demo_today: str | None = Field(default=None, alias="DEMO_TODAY")

    data_dir: Path = Field(default=DATA_DIR)

    def is_production(self) -> bool:
        return self.env.strip().lower() in {"production", "prod"}

    def assert_secure_for_environment(self) -> None:
        """Refuse to start in production with a default/placeholder admin token."""
        if not self.is_production():
            return
        token = self.admin_api_token.strip()
        if token in INSECURE_ADMIN_TOKENS or len(token) < 16:
            raise RuntimeError(
                "Refusing to start: ENV=production requires a strong ADMIN_API_TOKEN "
                "(not a default/placeholder, at least 16 characters)."
            )

    smtp_host: str = Field(default="smtp.gmail.com", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    imap_host: str = Field(default="imap.gmail.com", alias="IMAP_HOST")
    imap_port: int = Field(default=993, alias="IMAP_PORT")
    imap_user: str = Field(default="", alias="IMAP_USER")
    imap_password: str = Field(default="", alias="IMAP_PASSWORD")
    email_from_name: str = Field(default="AcmeCorp Accounts Team", alias="EMAIL_FROM_NAME")
    reminder_cooldown_hours: int = Field(default=24, alias="REMINDER_COOLDOWN_HOURS")

    llm_provider: str = Field(default="openai_compatible", alias="LLM_PROVIDER")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta/openai/",
        alias="LLM_BASE_URL",
    )
    llm_model: str = Field(default="gemini-2.0-flash", alias="LLM_MODEL")

    match_use_embeddings: bool = Field(default=False, alias="MATCH_USE_EMBEDDINGS")
    match_use_llm: bool = Field(default=False, alias="MATCH_USE_LLM")


@lru_cache
def get_settings() -> Settings:
    return Settings()
