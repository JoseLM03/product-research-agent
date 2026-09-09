from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    environment: Literal["development", "production", "test"] = "development"
    database_url: str = "sqlite:///./research.db"
    session_secret: str = "development-only-change-before-deploying"
    app_origin: str = "http://127.0.0.1:3000"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    brave_api_key: str = ""
    research_enabled: bool = False
    daily_global_limit: int = Field(default=20, ge=1, le=1000)
    daily_session_limit: int = Field(default=5, ge=1, le=100)
    daily_ip_limit: int = Field(default=10, ge=1, le=200)
    max_tool_calls: int = Field(default=10, ge=2, le=20)
    job_timeout_seconds: int = Field(default=300, ge=10, le=600)
    worker_enabled: bool = True
    static_dir: str = "dist/client"
    retention_days: int = Field(default=30, ge=1, le=365)

    @model_validator(mode="after")
    def production(self):
        if self.environment == "production":
            if len(self.session_secret) < 32 or self.session_secret.startswith("development"):
                raise ValueError(
                    "Production requires a random SESSION_SECRET of at least 32 characters"
                )
            if not self.app_origin.startswith("https://"):
                raise ValueError("Production APP_ORIGIN must use HTTPS")
            if not self.database_url.startswith("postgresql"):
                raise ValueError("Production requires PostgreSQL")
        self.app_origin = self.app_origin.rstrip("/")
        return self

    @property
    def configured(self):
        return self.research_enabled and bool(self.brave_api_key)
