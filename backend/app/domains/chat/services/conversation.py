"""接收用户输入，并把会话变化与 USER 消息原子持久化。

该 service 是 completion 的业务事务入口。它确认系统已经接受用户轮次，并在新会话
事务提交后提交轻量标题任务；它不启动 Graph，也不创建 SSE 流。
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.domains.chat.repositories import ConversationRepository
from app.domains.chat.services.completion_lock import (
    acquire_completion_lock,
    release_completion_lock,
)
from app.domains.chat.services.title import (
    TitleGenerationRequest,
    submit_title_generation,
)
from app.domains.chat.shared.models import (
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
)


class ConversationNotFound(Exception):
    """表示目标会话不存在，或不属于当前用户。

    两种情况共用同一领域错误，避免上层 API 暴露其他用户会话是否真实存在。
    """


@dataclass(frozen=True, slots=True)
class AcceptedUserTurn:
    """已经提交的用户轮次，是启动 Graph 所需的最小稳定输入。"""

    conversation_id: int
    user_message_id: int
    content: str


@dataclass(frozen=True, slots=True)
class AcceptedCompletion:
    """已提交的用户轮次及其仍由 completion lifecycle 持有的分布式锁。"""

    turn: AcceptedUserTurn
    lock: Any


def _normalize_content(content: str) -> str:
    """去除首尾空白并拒绝空内容，确保标题与消息使用同一规范化文本。"""

    normalized = content.strip()
    if not normalized:
        raise ValueError("content must not be blank")
    return normalized


def _title_from_content(content: str) -> str:
    """从首条规范化消息截取 20 个字符作为新会话临时标题。"""

    return content[:20]


class ConversationService:
    """管理“创建或复用会话并追加 USER 消息”的单一业务事务。"""

    def __init__(
        self,
        session_factory: Any,
        id_generator: Any,
        title_model: Any,
        *,
        completion_lock_factory: Any,
        title_submitter: Any = submit_title_generation,
        now: Any = None,
    ) -> None:
        self._session_factory = session_factory
        self._id_generator = id_generator
        self._title_model = title_model
        self._completion_lock_factory = completion_lock_factory
        self._title_submitter = title_submitter
        self._now = now or (lambda: datetime.now(UTC))

    async def accept_user_turn(
        self,
        *,
        user_id: str,
        content: str,
        conversation_id: int | None = None,
    ) -> AcceptedCompletion:
        """接受一轮用户输入并返回已提交的业务标识。

        未提供 ``conversation_id`` 时创建 ACTIVE 会话；提供 ID 时只允许更新当前用户
        拥有且未删除的会话。会话变化和 USER 消息处于同一事务，任一步失败都会整体
        回滚，调用方因此可以安全地把成功返回视为启动 Graph 的前置条件。
        """

        # 步骤 1：在打开数据库事务前规范化输入，空内容不会产生任何持久化副作用。
        normalized = _normalize_content(content)
        is_new_conversation = conversation_id is None
        title_request: TitleGenerationRequest | None = None
        completion_lock: Any | None = None
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    timestamp = self._now()

                    # 步骤 2：先解析 owner 或分配新 ID，再在任何业务写入前取得整轮锁。
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
                    else:
                        conversation = await ConversationRepository(session).get_owned(
                            conversation_id=conversation_id,
                            user_id=user_id,
                        )
                        if conversation is None:
                            raise ConversationNotFound()

                    completion_lock = await acquire_completion_lock(
                        self._completion_lock_factory,
                        conversation_id=conversation_id,
                    )

                    if is_new_conversation:
                        session.add(conversation)
                        title_request = TitleGenerationRequest(
                            conversation_id=conversation_id,
                            content=normalized,
                        )
                    else:
                        conversation.updated_at = timestamp

                    # 步骤 3：在同一事务追加 USER 消息，确保会话与首轮输入不会部分提交。
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

            # 只有事务上下文正常退出后才启动标题 task，保证会话和 USER 消息已经提交。
            if title_request is not None:
                self._title_submitter(
                    request=title_request,
                    model=self._title_model,
                    session_factory=self._session_factory,
                )
        except BaseException:
            if completion_lock is not None:
                await release_completion_lock(completion_lock)
            raise

        # 只有事务上下文正常退出后才把稳定 ID 交给 Graph producer。
        return AcceptedCompletion(
            turn=AcceptedUserTurn(
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                content=normalized,
            ),
            lock=completion_lock,
        )
