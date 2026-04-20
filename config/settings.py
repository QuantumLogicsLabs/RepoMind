from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # LLM
    openai_api_key: str
    llm_model:      str = "gpt-4o"
    max_plan_steps: int = 15

    # GitHub
    github_token:    str
    github_username: str

    # App
    app_env:   str = "development"
    log_level: str = "INFO"

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
