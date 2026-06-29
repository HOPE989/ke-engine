from functools import lru_cache

from fastapi import status
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.core.exceptions import AppException

_DEFAULT_MODEL = "gpt-4o-mini"


@lru_cache(maxsize=1)
def get_chat_model() -> ChatOpenAI:
    settings = get_settings()
    api_key = _clean_value(settings.openai_api_key)
    if api_key is None:
        raise AppException(
            "OPENAI_API_KEY is required",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    model = _clean_value(settings.openai_model) or _DEFAULT_MODEL
    base_url = _clean_value(settings.openai_base_url)
    kwargs: dict[str, str] = {
        "api_key": api_key,
        "model": model,
    }
    if base_url is not None:
        kwargs["base_url"] = base_url

    return ChatOpenAI(**kwargs)


def _clean_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class ChatService:
    async def chat(self, message: str) -> str:
        try:
            response = await get_chat_model().ainvoke(message)
        except AppException:
            raise
        except Exception as exc:
            raise AppException(
                "chat provider request failed",
                status_code=status.HTTP_502_BAD_GATEWAY,
            ) from exc

        return str(response.content)

    def _create_chat_model(self) -> ChatOpenAI:
        return get_chat_model()
