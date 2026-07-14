"""OpenAI-compatible 模型基础设施工厂。"""

from typing import Any

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

EMBEDDING_MODEL = "text-embedding-v4"
EMBEDDING_CHUNK_SIZE = 9


def create_chat_model(settings: Any, *, model: str) -> ChatOpenAI:
    """按运行配置创建指定模型的 ChatOpenAI client。"""

    api_key = _clean_value(getattr(settings, "openai_api_key", None))
    if api_key is None:
        raise RuntimeError("OPENAI_API_KEY is required")

    kwargs: dict[str, str] = {
        "api_key": api_key,
        "model": model,
    }
    base_url = _clean_value(getattr(settings, "openai_base_url", None))
    if base_url is not None:
        kwargs["base_url"] = base_url
    return ChatOpenAI(**kwargs)


def create_embedding_model(settings: Any) -> OpenAIEmbeddings:
    """创建文档向量存储使用的 OpenAI-compatible embedding model。"""

    return OpenAIEmbeddings(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=EMBEDDING_MODEL,
        chunk_size=EMBEDDING_CHUNK_SIZE,
        dimensions=settings.embedding_dimensions,
        check_embedding_ctx_length=False,
    )


def _clean_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
