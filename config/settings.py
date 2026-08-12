"""config/settings.py

Pydantic BaseSettings for RepoMind.

 task-10-persistent-jobs
Supports both Groq (primary, free) and OpenAI (fallback) backends.

Supports only Groq backend with API Key Rotation support.
Multiple keys can be provided separated by commas to avoid 429 Rate Limits.

Also provides small resolver helpers so request-scoped credentials (from
api/schemas.RunRequest) can override the server's own defaults without
ever being written back into Settings or logged.
 main
"""

from __future__ import annotations

import os
import threading
from functools import lru_cache

 task-10-persistent-jobs
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ─────────────────────────────────────────────────────────────
    # LLM - Groq
    # ─────────────────────────────────────────────────────────────
    groq_api_key: str | None = None
    llm_model: str = "llama-3.3-70b-versatile"

    # ─────────────────────────────────────────────────────────────
    # LLM - OpenAI
    # ─────────────────────────────────────────────────────────────
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"

    # ─────────────────────────────────────────────────────────────
    # Plan
    # ─────────────────────────────────────────────────────────────
    max_plan_steps: int = 10

    # ─────────────────────────────────────────────────────────────
    # GitHub
    # ─────────────────────────────────────────────────────────────
    github_token: str | None = None
    github_username: str | None = None

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── LLM — Groq (primary, free, fast) ─────────────────────────────────────
    # Can be a single key, or multiple keys separated by commas for rotation
    groq_api_key: str = ""
    llm_model: str = "llama-3.3-70b-versatile"

    # ── Plan limits ───────────────────────────────────────────────────────────
    max_plan_steps: int = 10

    # ── GitHub (server-wide default; requests may override per-job) ──────────
    github_token: SecretStr | None = None
    github_username: str = ""
 main

    # ─────────────────────────────────────────────────────────────
    # App
    # ─────────────────────────────────────────────────────────────
    app_env: str = "development"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    @property
    def parsed_groq_keys(self) -> list[str]:
        """Parse comma-separated keys into a list for rotation."""
        return [k.strip() for k in self.groq_api_key.split(",") if k.strip()]

    @model_validator(mode="after")
 task-10-persistent-jobs
    def validate_settings(self) -> Settings:
        """
        Validate required settings after loading environment variables.
        """

        if not self.groq_api_key and not self.openai_api_key:
            raise ValueError(
                "At least one LLM API key must be provided " "(GROQ_API_KEY or OPENAI_API_KEY)."
            )

        if not self.github_token:
            raise ValueError("GITHUB_TOKEN is required.")

        if not self.github_username:
            raise ValueError("GITHUB_USERNAME is required.")


    def check_groq_key(self) -> Settings:
        """Fail fast at startup if no Groq backend is configured."""
        if not self.parsed_groq_keys:
            raise ValueError(
                "GROQ_API_KEY must be set in your environment variables. "
                "You can provide multiple keys separated by commas."
            )
 main
        return self

    @property
    def active_llm_model(self) -> str:
 task-10-persistent-jobs
        if self.openai_api_key:
            return self.openai_model

        """Return the model name appropriate for the active backend."""
 main
        return self.llm_model

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    # ── Request-scoped credential resolution ─────────────────────────────────

    def resolve_llm_credentials(
        self,
        request_provider: str | None,
        request_api_key: SecretStr | None,
    ) -> tuple[str, str]:
        """
        Decide which LLM provider + key to actually use for one job.

        This project supports Groq only. request_provider is accepted for
        forward-compatibility but must be "groq" (or omitted). A request-scoped
        key takes priority over the server's rotating key pool; when no request
        key is supplied, the next key from groq_key_rotator is used.

        Returns:
            (provider, plain_api_key_string) — the plain string is only ever
            held in memory for the duration of one job, never stored or logged.

        Raises:
            ValueError: If request_provider is anything other than "groq",
                        or if no usable key is available.
        """
        provider = (request_provider or "groq").lower()
        if provider != "groq":
            raise ValueError(
                f"Unsupported llm_provider: '{provider}'. This project runs on Groq only."
            )

        if request_api_key is not None:
            return provider, request_api_key.get_secret_value()

        return provider, groq_key_rotator.get_key()

    def resolve_github_token(self, request_token: SecretStr | None) -> str:
        """
        Decide which GitHub token to actually use for one job.

        Request-scoped token takes priority over the server default.

        Raises:
            ValueError: If no token is available from either source.
        """
        if request_token is not None:
            return request_token.get_secret_value()
        if self.github_token:
            return self.github_token.get_secret_value()
        raise ValueError(
            "No GitHub token available (no request token supplied, "
            "no server default configured)."
        )


@lru_cache
def get_settings() -> Settings:
 task-10-persistent-jobs
    return Settings()

    """Return a cached Settings instance (parsed once per process)."""
    return Settings(groq_api_key=os.getenv("GROQ_API_KEY") or "local-dev-key")


# --- API Key Rotation Helper ---


class GroqKeyRotator:
    """Thread-safe key rotator for handling 429 Rate Limits.

    Cycles through all available keys provided in GROQ_API_KEY.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._index = 0
        self._keys: list[str] | None = None

    def get_key(self) -> str:
        """Get the next available Groq API Key."""
        with self._lock:
            if self._keys is None:
                # Load keys lazily on first request
                self._keys = get_settings().parsed_groq_keys

            key = self._keys[self._index]
            # Move to the next key for the next request (Round-robin)
            self._index = (self._index + 1) % len(self._keys)
            return key


# Global instance to be used by the agent/LLM initialisation layer
groq_key_rotator = GroqKeyRotator()
 main
