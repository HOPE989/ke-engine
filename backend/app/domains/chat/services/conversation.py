"""接收并持久化用户轮次。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.domains.chat.repositories import ConversationRepository
from app.domains.chat.shared.models import (
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
)


class ConversationNotFound(Exception):
    """会话不存在或不属于当前用户。"""


@dataclass(frozen=True, slots=True)
class AcceptedUserTurn:
    conversation_id: int
    user_message_id: int
    content: str


def _normalize_content(content: str) -> str:
    normalized = content.strip()
    if not normalized:
        raise ValueError("content must not be blank")
    return normalized


def _title_from_content(content: str) -> str:
    return content[:255]


class ConversationService:
    def __init__(
        self,
        session_factory: Any,
        id_generator: Any,
        *,
        now: Any = None,
    ) -> None:
        self._session_factory = session_factory
        self._id_generator = id_generator
        self._now = now or (lambda: datetime.now(UTC))

    async def accept_user_turn(
        self,
        *,
        user_id: str,
        content: str,
        conversation_id: int | None = None,
    ) -> AcceptedUserTurn:
        normalized = _normalize_content(content)
        async with self._session_factory() as session:
            async with session.begin():
                timestamp = self._now()
                if conversation_id is None:
                    conversation_id = self._id_generator.next_id()
                    conversation = Conversation(
                        id=conversation_id,
                        user_id=user_id,
                        title=_title_from_content(normalized),
                        status=ConversationStatus.ACTIVE.value,
                        created_at=timestamp,
                        updated_at=timestamp,
                    )
                    session.add(conversation)
                else:
                    conversation = await ConversationRepository(session).get_owned(
                        conversation_id=conversation_id,
                        user_id=user_id,
                    )
                    if conversation is None:
                        raise ConversationNotFound()
                    conversation.updated_at = timestamp

                user_message_id = self._id_generator.next_id()
                session.add(
                    Message(
                        id=user_message_id,
                        conversation_id=conversation_id,
                        role=MessageRole.USER.value,
                        content=normalized,
                        created_at=timestamp,
                        updated_at=timestamp,
                    )
                )

        return AcceptedUserTurn(
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            content=normalized,
        )
