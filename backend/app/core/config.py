from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    app_name: str = "ke-engine"
    app_version: str = "0.1.0"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://ke_engine:ke_engine@localhost:5432/ke_engine"
    password_hash_iterations: int = 260_000
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_base_url: str | None = Field(default=None, validation_alias="OPENAI_BASE_URL")
    openai_model: str | None = Field(default=None, validation_alias="OPENAI_MODEL")

    model_config = SettingsConfigDict(
        env_prefix="KE_ENGINE_",
        extra="ignore",
    )


def create_settings(env_file: Path | None = None) -> Settings:
    return Settings(_env_file=env_file or DEFAULT_ENV_FILE)


@lru_cache
def get_settings() -> Settings:
    return create_settings()
