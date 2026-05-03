from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    # LLM — Groq (free, fast)
    groq_api_key: str

    # LLM — OpenAI (optional fallback)
    openai_api_key: Optional[str] = None
    llm_model: str = "llama-3.3-70b-versatile"
    max_plan_steps: int = 15

    # GitHub
    github_token: str
    github_username: str

    # App
    app_env: str = "development"
    log_level: str = "INFO"

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
