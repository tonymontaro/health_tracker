from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / ".emv"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://health:health@localhost:55432/health"
    app_base_url: str = "http://localhost:5173"
    api_base_url: str = "http://localhost:8000"
    app_timezone: str = "Europe/Zurich"
    cors_allowed_origins: str = "http://localhost:5173"

    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "OPEN_AI_API_KEY"),
    )
    openai_planner_model: str = "gpt-5.6-terra"
    openai_qa_model: str = "gpt-5.6-luna"
    openai_food_log_model: str = "gpt-5.6-luna"
    openai_reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] = "medium"

    resend_api_key: SecretStr | None = None
    resend_from: str | None = None
    resend_to: str | None = None

    session_secret: SecretStr = SecretStr("development-only-session-secret-change-me")
    session_cookie_name: str = "health_session"
    session_days: int = 30
    bootstrap_email: str = "owner@localhost"
    bootstrap_password: SecretStr = SecretStr("change-me-now")
    extension_api_token: SecretStr | None = None

    coop_online_minimum_chf: float = 100
    migros_online_minimum_chf: float = 100

    @field_validator("database_url")
    @classmethod
    def normalize_postgres_scheme(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @model_validator(mode="after")
    def reject_development_secrets_in_production(self) -> "Settings":
        if self.app_env != "production":
            return self
        unsafe: list[str] = []
        if self.session_secret.get_secret_value() == "development-only-session-secret-change-me":
            unsafe.append("SESSION_SECRET")
        if self.bootstrap_password.get_secret_value() == "change-me-now":
            unsafe.append("BOOTSTRAP_PASSWORD")
        if not self.resend_api_key:
            unsafe.append("RESEND_API_KEY")
        if not self.resend_from:
            unsafe.append("RESEND_FROM")
        if not self.resend_to:
            unsafe.append("RESEND_TO")
        if unsafe:
            raise ValueError("Production requires secure configuration for " + ", ".join(unsafe))
        return self

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def openai_key_value(self) -> str | None:
        return self.openai_api_key.get_secret_value() if self.openai_api_key else None

    @property
    def resend_key_value(self) -> str | None:
        return self.resend_api_key.get_secret_value() if self.resend_api_key else None

    @property
    def resend_configured(self) -> bool:
        return bool(self.resend_key_value and self.resend_from and self.resend_to)


@lru_cache
def get_settings() -> Settings:
    return Settings()
