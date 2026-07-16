"""应用配置加载。

配置优先从环境变量读取，其次从 backend/.env 加载用户必须配置的值，
再从 backend/config.yaml 加载非敏感运行默认值。
"""

from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import YamlConfigSettingsSource

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = BACKEND_DIR / ".env"
DEFAULT_CONFIG_FILE = BACKEND_DIR / "config.yaml"
_CONFIG_FILE_OVERRIDE: ContextVar[Path | None] = ContextVar(
    "CONFIG_FILE_OVERRIDE",
    default=None,
)


class Settings(BaseSettings):
    """运行时配置对象。"""

    app_name: str = "ke-engine"
    app_version: str = "0.1.0"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    database_url: str = Field(
        default="postgresql+asyncpg://ke_engine:ke_engine@localhost:5432/ke_engine",
        validation_alias="DATABASE_URL",
        description="startup-only: database engine and session factory are created during lifespan startup.",
    )
    max_upload_size_mb: int = Field(
        default=20,
        validation_alias="MAX_UPLOAD_SIZE_MB",
        description="request-time: upload validation reads this on each request.",
    )
    minio_endpoint: str = Field(
        default="localhost:9000",
        validation_alias="MINIO_ENDPOINT",
        description="startup-only: MinIO client is created during lifespan startup.",
    )
    minio_access_key: str = Field(
        default="minioadmin",
        validation_alias="MINIO_ACCESS_KEY",
        description="startup-only: MinIO client is created during lifespan startup.",
    )
    minio_secret_key: str = Field(
        default="minioadmin",
        validation_alias="MINIO_SECRET_KEY",
        description="startup-only: MinIO client is created during lifespan startup.",
    )
    minio_bucket: str = Field(
        default="documents",
        validation_alias="MINIO_BUCKET",
        description="startup-only: document object storage is created during lifespan startup.",
    )
    minio_public_base_url: str = Field(
        default="http://localhost:9000",
        validation_alias="MINIO_PUBLIC_BASE_URL",
        description="startup-only: document object storage is created during lifespan startup.",
    )
    minio_secure: bool = Field(
        default=False,
        validation_alias="MINIO_SECURE",
        description="startup-only: MinIO client is created during lifespan startup.",
    )
    mineru_base_url: str = Field(
        default="http://localhost:8000",
        validation_alias="MINERU_BASE_URL",
        description="startup-only: MinerU client is cached on app.state after first use.",
    )
    mineru_provider: str = Field(
        default="local",
        validation_alias="MINERU_PROVIDER",
        description="startup-only: MinerU provider factory selects local or official at application startup.",
    )
    mineru_api_key: str | None = Field(
        default=None,
        validation_alias="MINERU_API_KEY",
        description="startup-only: MinerU API authentication is configured during client creation.",
    )
    mineru_model_version: str = Field(
        default="vlm",
        validation_alias="MINERU_MODEL_VERSION",
        description="startup-only: official MinerU parsing model is fixed for the process lifetime.",
    )
    mineru_poll_interval_seconds: float = Field(
        default=2,
        validation_alias="MINERU_POLL_INTERVAL_SECONDS",
        description="startup-only: official MinerU polling cadence is fixed for the process lifetime.",
    )
    mineru_poll_timeout_seconds: float = Field(
        default=300,
        validation_alias="MINERU_POLL_TIMEOUT_SECONDS",
        description="startup-only: official MinerU polling timeout is fixed for the process lifetime.",
    )
    mineru_timeout_seconds: int = Field(
        default=60,
        validation_alias="MINERU_TIMEOUT_SECONDS",
        description="startup-only: MinerU client is cached on app.state after first use.",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias="REDIS_URL",
        description="startup-only: Redis client is created for document conversion locks.",
    )
    kafka_bootstrap_servers: str = Field(
        default="localhost:9092",
        validation_alias="KAFKA_BOOTSTRAP_SERVERS",
        description="startup-only: Kafka clients are configured during process startup.",
    )
    document_convert_lock_expire_seconds: int = Field(
        default=120,
        validation_alias="DOCUMENT_CONVERT_LOCK_EXPIRE_SECONDS",
        description="startup-only: document conversion Redis lock expiry is fixed for workers.",
    )
    snowflake_worker_id: int = Field(
        default=1,
        validation_alias="SNOWFLAKE_WORKER_ID",
        description="startup-only: Snowflake worker id is fixed for generated document ids.",
    )
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_base_url: str | None = Field(default=None, validation_alias="OPENAI_BASE_URL")
    openai_model: str | None = Field(
        default=None,
        validation_alias="OPENAI_MODEL",
        description="startup-only: Chat model is fixed for the Chat API process lifetime.",
    )
    elasticsearch_url: str = Field(
        default="http://localhost:9200",
        validation_alias="ELASTICSEARCH_URL",
        description=(
            "startup-only: Elasticsearch vector store client is configured during "
            "vector-storage worker startup."
        ),
    )
    elasticsearch_index: str = Field(
        default="ke-engine-vector",
        validation_alias="ELASTICSEARCH_INDEX",
        description=(
            "startup-only: vector-storage workers write all segment vectors to this "
            "Elasticsearch index."
        ),
    )
    embedding_dimensions: int = Field(
        default=1536,
        validation_alias="EMBEDDING_DIMENSIONS",
        description=(
            "startup-only: embedding dimensions must match OpenAIEmbeddings and the "
            "Elasticsearch dense_vector mapping."
        ),
    )

    model_config = SettingsConfigDict(
        env_prefix="KE_ENGINE_",
        extra="ignore",
        populate_by_name=True,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        config_file = _CONFIG_FILE_OVERRIDE.get() or DEFAULT_CONFIG_FILE
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls, yaml_file=config_file),
            file_secret_settings,
        )


STARTUP_ONLY_SETTINGS = {
    "database_url",
    "minio_endpoint",
    "minio_access_key",
    "minio_secret_key",
    "minio_bucket",
    "minio_public_base_url",
    "minio_secure",
    "mineru_base_url",
    "mineru_provider",
    "mineru_api_key",
    "mineru_model_version",
    "mineru_poll_interval_seconds",
    "mineru_poll_timeout_seconds",
    "mineru_timeout_seconds",
    "redis_url",
    "kafka_bootstrap_servers",
    "document_convert_lock_expire_seconds",
    "snowflake_worker_id",
    "elasticsearch_url",
    "elasticsearch_index",
    "embedding_dimensions",
    "openai_model",
}
REQUEST_TIME_SETTINGS = {"max_upload_size_mb"}


def create_settings(
    env_file: Path | None = None,
    config_file: Path | None = None,
) -> Settings:
    """从 env 文件和 YAML 配置文件创建配置。"""

    token = _CONFIG_FILE_OVERRIDE.set(config_file or DEFAULT_CONFIG_FILE)
    try:
        return Settings(_env_file=env_file or DEFAULT_ENV_FILE)
    finally:
        _CONFIG_FILE_OVERRIDE.reset(token)


@lru_cache
def get_settings() -> Settings:
    """返回进程级缓存配置对象。"""

    return create_settings()


def get_request_settings() -> Settings:
    """返回请求期配置快照，用于允许请求边界字段不重启生效。"""

    return create_settings()


def validate_chat_startup_settings(settings: Settings) -> Settings:
    """确认 Chat API 启动所需、但其他进程可省略的配置。"""

    if not settings.openai_model or not settings.openai_model.strip():
        raise ValueError("OPENAI_MODEL is required to start the Chat API")
    return settings
