"""会话标题的轻量异步生成与 best-effort 持久化。"""

import asyncio
from dataclasses import dataclass
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.domains.chat.repositories import ConversationRepository

TITLE_MODEL = "qwen3.6-flash"
TITLE_MAX_LENGTH = 20
TITLE_SYSTEM_PROMPT = (
    "根据用户消息概括会话主题。只输出标题，不要解释，不要添加引号，最多20个字符。"
)

_TITLE_PREFIX = re.compile(r"^标题\s*[:：]\s*")
_OUTER_QUOTES = (("\"", "\""), ("'", "'"), ("“", "”"), ("‘", "’"))
_background_title_tasks: set[asyncio.Task[None]] = set()
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TitleGenerationRequest:
    conversation_id: int
    content: str


def _extract_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "".join(parts)


def normalize_title(content: object) -> str:
    """把模型响应清洗成最多 20 个字符的纯标题。"""

    text = _extract_text(content).strip()
    if not text:
        return ""
    text = text.splitlines()[0].strip()
    text = _TITLE_PREFIX.sub("", text).strip()
    for opening, closing in _OUTER_QUOTES:
        if len(text) >= 2 and text.startswith(opening) and text.endswith(closing):
            text = text[len(opening) : -len(closing)].strip()
            break
    return text[:TITLE_MAX_LENGTH]


async def generate_and_update_title(
    *,
    request: TitleGenerationRequest,
    model: Any,
    session_factory: Any,
) -> None:
    """生成并 best-effort 更新标题；普通失败不得逃逸到主请求。"""

    try:
        response = await model.ainvoke(
            [
                SystemMessage(content=TITLE_SYSTEM_PROMPT),
                HumanMessage(content=request.content),
            ]
        )
        title = normalize_title(response.content)
        if not title:
            return

        async with session_factory() as session:
            async with session.begin():
                await ConversationRepository(session).update_title(
                    conversation_id=request.conversation_id,
                    title=title,
                )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(
            "conversation title generation failed",
            extra={"conversation_id": request.conversation_id},
        )


def submit_title_generation(
    *,
    request: TitleGenerationRequest,
    model: Any,
    session_factory: Any,
) -> asyncio.Task[None]:
    """在当前事件循环直接创建标题 task，并在完成前保持强引用。"""

    task = asyncio.create_task(
        generate_and_update_title(
            request=request,
            model=model,
            session_factory=session_factory,
        ),
        name=f"conversation-title:{request.conversation_id}",
    )
    _background_title_tasks.add(task)
    task.add_done_callback(_background_title_tasks.discard)
    return task
