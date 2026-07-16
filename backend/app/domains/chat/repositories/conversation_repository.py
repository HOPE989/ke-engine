"""基于 owner scope 的会话读取与 keyset pagination。

业务会话历史只来自 ``conversations`` 表，不从 LangGraph checkpoint 反向组装。所有
查询都同时限制 ``user_id`` 和非删除状态，避免跨用户读取。
"""

import base64
from dataclasses import dataclass
from datetime import datetime
import json

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.chat.shared.models import Conversation, ConversationStatus


@dataclass(frozen=True, slots=True)
class ConversationCursor:
    """会话倒序分页边界，由 ``updated_at`` 与 ``id`` 共同保证稳定顺序。"""

    updated_at: datetime
    id: int

    def encode(self) -> str:
        """把时间和 ID 编码为可放入查询参数的无填充 URL-safe Base64。"""

        payload = json.dumps(
            [self.updated_at.isoformat(), self.id],
            separators=(",", ":"),
        ).encode()
        return base64.urlsafe_b64encode(payload).decode().rstrip("=")

    @classmethod
    def decode(cls, value: str) -> "ConversationCursor":
        """从查询参数恢复会话分页边界。"""

        padded = value + "=" * (-len(value) % 4)
        updated_at, identifier = json.loads(base64.urlsafe_b64decode(padded))
        return cls(datetime.fromisoformat(updated_at), int(identifier))


def _before_cursor(cursor: ConversationCursor):
    """构造倒序列表中位于 cursor 之后的 SQL keyset 条件。"""

    return or_(
        Conversation.updated_at < cursor.updated_at,
        and_(
            Conversation.updated_at == cursor.updated_at,
            Conversation.id < cursor.id,
        ),
    )


class ConversationRepository:
    """封装当前用户可见会话的持久化查询。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_owned(self, *, conversation_id: int, user_id: str) -> Conversation | None:
        """按 ID 读取当前用户拥有且未删除的会话。"""

        statement = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.status != ConversationStatus.DELETED.value,
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def update_title(self, *, conversation_id: int, title: str) -> bool:
        """更新未删除会话的标题，同时保持业务活跃时间不变。"""

        statement = (
            update(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.status != ConversationStatus.DELETED.value,
            )
            .values(
                title=title,
                updated_at=Conversation.updated_at,
            )
        )
        result = await self._session.execute(statement)
        return result.rowcount > 0

    async def list_owned(
        self,
        *,
        user_id: str,
        limit: int,
        cursor: str | None = None,
    ) -> tuple[list[Conversation], str | None]:
        """按 ``(updated_at DESC, id DESC)`` 返回一页当前用户会话。

        多取一条记录只用于判断是否存在下一页；响应 items 始终不超过 ``limit``，
        下一 cursor 取自本页最后一条记录，避免 offset 在并发更新下产生重复或遗漏。
        """

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
