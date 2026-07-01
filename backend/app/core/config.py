"""应用配置加载。

配置优先从环境变量读取，也可从 backend/.env 加载本地开发默认值。
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    """运行时配置对象。"""

    app_name: str = "ke-engine"
    app_version: str = "0.1.0"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    database_url: str = Field(
        default="postgresql+asyncpg://ke_engine:ke_engine@localhost:5432/ke_engine",
        validation_alias="DATABASE_URL",
    )
    max_upload_size_mb: int = Field(default=20, validation_alias="MAX_UPLOAD_SIZE_MB")
    minio_endpoint: str = Field(default="localhost:9000", validation_alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(default="minioadmin", validation_alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(default="minioadmin", validation_alias="MINIO_SECRET_KEY")
    minio_bucket: str = Field(default="documents", validation_alias="MINIO_BUCKET")
    minio_public_base_url: str = Field(
        default="http://localhost:9000",
        validation_alias="MINIO_PUBLIC_BASE_URL",
    )
    minio_secure: bool = Field(default=False, validation_alias="MINIO_SECURE")
    mineru_base_url: str = Field(default="http://localhost:8000", validation_alias="MINERU_BASE_URL")
    mineru_timeout_seconds: int = Field(default=60, validation_alias="MINERU_TIMEOUT_SECONDS")
    password_hash_iterations: int = 260_000
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_base_url: str | None = Field(default=None, validation_alias="OPENAI_BASE_URL")
    openai_model: str | None = Field(default=None, validation_alias="OPENAI_MODEL")

    model_config = SettingsConfigDict(
        env_prefix="KE_ENGINE_",
        extra="ignore",
    )


def create_settings(env_file: Path | None = None) -> Settings:
    """从显式 env 文件或默认 backend/.env 创建配置。"""

    return Settings(_env_file=env_file or DEFAULT_ENV_FILE)


@lru_cache
def get_settings() -> Settings:
    """返回进程级缓存配置对象。"""

    return create_settings()
