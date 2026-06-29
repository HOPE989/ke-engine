from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ke-engine"
    app_version: str = "0.1.0"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://ke_engine:ke_engine@localhost:5432/ke_engine"
    password_hash_iterations: int = 260_000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="KE_ENGINE_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

