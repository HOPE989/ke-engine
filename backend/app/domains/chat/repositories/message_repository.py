"""Owner-scoped message history 查询。"""

import base64
from dataclasses import dataclass
from datetime import datetime
import json

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.chat.shared.models import Conversation, ConversationStatus, Message


@dataclass(frozen=True, slots=True)
class MessageCursor:
    created_at: datetime
    id: int

    def encode(self) -> str:
        payload = json.dumps(
            [self.created_at.isoformat(), self.id],
            separators=(",", ":"),
        ).encode()
        return base64.urlsafe_b64encode(payload).decode().rstrip("=")

    @classmethod
    def decode(cls, value: str) -> "MessageCursor":
        padded = value + "=" * (-len(value) % 4)
        created_at, identifier = json.loads(base64.urlsafe_b64decode(padded))
        return cls(datetime.fromisoformat(created_at), int(identifier))


def _after_cursor(cursor: MessageCursor):
    return or_(
        Message.created_at > cursor.created_at,
        and_(
            Message.created_at == cursor.created_at,
            Message.id > cursor.id,
        ),
    )


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_owned(
        self,
        *,
        user_id: str,
        conversation_id: int,
        limit: int,
        cursor: str | None = None,
    ) -> tuple[list[Message], str | None]:
        statement = (
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.conversation_id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.status != ConversationStatus.DELETED.value,
            )
        )
        if cursor is not None:
            boundary = MessageCursor.decode(cursor)
            statement = statement.where(_after_cursor(boundary))
        statement = statement.order_by(Message.created_at.asc(), Message.id.asc()).limit(
            limit + 1
        )
        rows = list((await self._session.execute(statement)).scalars().all())
        items = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            last = items[-1]
            next_cursor = MessageCursor(last.created_at, last.id).encode()
        return items, next_cursor
