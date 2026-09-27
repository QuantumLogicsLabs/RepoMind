"""config/settings.py

Pydantic BaseSettings for RepoMind.

Supports only Groq backend with API Key Rotation support.
Multiple keys can be provided separated by commas to avoid 429 Rate Limits.

Also provides small resolver helpers so request-scoped credentials (from
api/schemas.RunRequest) can override the server's own defaults without
ever being written back into Settings or logged.
"""

from __future__ import annotations

import os
import threading
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings

# Load RepoMind/.env into the process environment. Must happen before
# get_settings() reads os.getenv("GROQ_API_KEY") below — without this,
# api/main.py never loads .env and the key silently falls back to the
# invalid "local-dev-key" placeholder.
load_dotenv()


class Settings(BaseSettings):
    # ── LLM — Groq (primary, free, fast) ─────────────────────────────────────
    # Can be a single key, or multiple keys separated by commas for rotation
    groq_api_key: str = ""
    llm_model: str = "openai/gpt-oss-120b"

    # ── Plan limits ───────────────────────────────────────────────────────────
    max_plan_steps: int = 10

    # ── GitHub (server-wide default; requests may override per-job) ──────────
    github_token: SecretStr | None = None
    github_username: str = ""

    # ── App ───────────────────────────────────────────────────────────────────
    app_env: str = "development"
    log_level: str = "INFO"

    # ── Semantic Memory ──────────────────────────────────────────────────────
    memory_storage_dir: str = ".repomind_memory"
    memory_dedup_threshold: float = 0.85

    # ── Plugins ───────────────────────────────────────────────────────────────
    plugins_dir: str = "plugins"
    enabled_plugins: list[str] = []

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def parsed_groq_keys(self) -> list[str]:
        """Parse comma-separated keys into a list for rotation."""
        return [k.strip() for k in self.groq_api_key.split(",") if k.strip()]

    @model_validator(mode="after")
    def check_groq_key(self) -> Settings:
        """Fail fast at startup if no Groq backend is configured."""
        if not self.parsed_groq_keys:
            raise ValueError(
                "GROQ_API_KEY must be set in your environment variables. "
                "You can provide multiple keys separated by commas."
            )
        return self

    @property
    def active_llm_model(self) -> str:
        """Return the model name appropriate for the active backend."""
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
