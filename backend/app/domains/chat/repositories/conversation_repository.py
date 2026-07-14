"""Owner-scoped conversation 查询。"""

import base64
from dataclasses import dataclass
from datetime import datetime
import json

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.chat.shared.models import Conversation, ConversationStatus


@dataclass(frozen=True, slots=True)
class ConversationCursor:
    updated_at: datetime
    id: int

    def encode(self) -> str:
        payload = json.dumps(
            [self.updated_at.isoformat(), self.id],
            separators=(",", ":"),
        ).encode()
        return base64.urlsafe_b64encode(payload).decode().rstrip("=")

    @classmethod
    def decode(cls, value: str) -> "ConversationCursor":
        padded = value + "=" * (-len(value) % 4)
        updated_at, identifier = json.loads(base64.urlsafe_b64decode(padded))
        return cls(datetime.fromisoformat(updated_at), int(identifier))


def _before_cursor(cursor: ConversationCursor):
    return or_(
        Conversation.updated_at < cursor.updated_at,
        and_(
            Conversation.updated_at == cursor.updated_at,
            Conversation.id < cursor.id,
        ),
    )


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_owned(
        self,
        *,
        user_id: str,
        limit: int,
        cursor: str | None = None,
    ) -> tuple[list[Conversation], str | None]:
        statement = select(Conversation).where(
            Conversation.user_id == user_id,
            Conversation.status != ConversationStatus.DELETED.value,
        )
        if cursor is not None:
            boundary = ConversationCursor.decode(cursor)
            statement = statement.where(_before_cursor(boundary))
        statement = statement.order_by(
            Conversation.updated_at.desc(),
            Conversation.id.desc(),
        ).limit(limit + 1)
        rows = list((await self._session.execute(statement)).scalars().all())
        items = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            last = items[-1]
            next_cursor = ConversationCursor(last.updated_at, last.id).encode()
        return items, next_cursor
