"""
config/settings.py

Pydantic BaseSettings for RepoMind.

Supports only Groq backend. A Groq API key must be provided — startup will
fail with a clear error if it is not set.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── LLM — Groq (primary, free, fast) ─────────────────────────────────────
    groq_api_key: str
    llm_model: str = "llama-3.3-70b-versatile"

    # ── Plan limits ───────────────────────────────────────────────────────────
    max_plan_steps: int = 10

    # ── GitHub ────────────────────────────────────────────────────────────────
    github_token: str = ""
    github_username: str = ""

    # ── App ───────────────────────────────────────────────────────────────────
    app_env: str = "development"
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        extra = "ignore"

    @model_validator(mode="after")
    def check_groq_key(self) -> "Settings":
        """Fail fast at startup if no Groq backend is configured."""
        if not self.groq_api_key:
            raise ValueError("GROQ_API_KEY must be set in your environment variables")
        return self

    @property
    def active_llm_model(self) -> str:
        """Return the model name appropriate for the active backend."""
        return self.llm_model

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (parsed once per process)."""
    return Settings()
