"""基于 owner scope 的业务消息写入与 keyset pagination。

消息历史查询通过 ``conversations`` 关联校验 owner，不读取 checkpoint 内部表；Graph
state 与面向用户的业务历史保持清晰分工。
"""

import base64
from dataclasses import dataclass
from datetime import datetime
import json

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.chat.shared.models import Conversation, ConversationStatus, Message


@dataclass(frozen=True, slots=True)
class MessageCursor:
    """消息正序分页边界，由 ``created_at`` 与 ``id`` 共同消除同毫秒歧义。"""

    created_at: datetime
    id: int

    def encode(self) -> str:
        """把时间和 ID 编码为无填充的 URL-safe Base64 cursor。"""

        payload = json.dumps(
            [self.created_at.isoformat(), self.id],
            separators=(",", ":"),
        ).encode()
        return base64.urlsafe_b64encode(payload).decode().rstrip("=")

    @classmethod
    def decode(cls, value: str) -> "MessageCursor":
        """从查询参数恢复消息分页边界。"""

        padded = value + "=" * (-len(value) % 4)
        created_at, identifier = json.loads(base64.urlsafe_b64decode(padded))
        return cls(datetime.fromisoformat(created_at), int(identifier))


def _after_cursor(cursor: MessageCursor):
    """构造正序历史中严格晚于 cursor 的 SQL keyset 条件。"""

    return or_(
        Message.created_at > cursor.created_at,
        and_(
            Message.created_at == cursor.created_at,
            Message.id > cursor.id,
        ),
    )


class MessageRepository:
    """封装 Chat 业务消息的写入和当前用户历史查询。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add_assistant(
        self,
        *,
        message_id: int,
        conversation_id: int,
        parent_message_id: int,
        content: str,
    ) -> Message:
        """把完整 ASSISTANT 回答加入当前业务事务。

        本方法只执行 ``session.add``，提交或回滚由调用方的事务上下文负责。
        """

        message = Message(
            id=message_id,
            conversation_id=conversation_id,
            parent_message_id=parent_message_id,
            role="ASSISTANT",
            content=content,
        )
        self._session.add(message)
        return message

    async def list_owned(
        self,
        *,
        user_id: str,
        conversation_id: int,
        limit: int,
        cursor: str | None = None,
    ) -> tuple[list[Message], str | None]:
        """按 ``(created_at ASC, id ASC)`` 返回一页会话消息。

        会话 owner 与非删除状态在同一 SQL 中校验。多取一条用于生成 next cursor，
        从而在不使用 offset 的情况下保持稳定的时间正序历史。
        """

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
