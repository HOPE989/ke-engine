"""Chat completion 的后台执行与实时订阅协调。

本模块把 Graph 执行任务的生命周期从 HTTP 请求协程中分离出来：请求只订阅实时
SSE 事件，producer 则负责完整消费 Graph、持久化最终回答并发布唯一终态。这样即使
客户端断开连接，已经接受的用户轮次仍可继续完成。
"""

import asyncio
from collections.abc import Callable
from typing import Any

from langchain_core.messages import HumanMessage

from app.contracts.chat.stream import CompletedPayload, ErrorPayload, MetadataPayload
from app.domains.chat.graph import ChatRuntimeContext
from app.domains.chat.repositories import MessageRepository
from app.domains.chat.services.conversation import AcceptedUserTurn
from app.services.chat_api.streaming import project_graph_event


class _CompletionChannel:
    """单次 completion 的进程内事件通道。

    channel 只服务当前 HTTP 连接，不承担跨进程重放。subscriber detach 后通过
    ``attached`` 阻止继续入队，避免无人消费的 token 占用内存，但不会反向取消 producer。
    """

    def __init__(self, *, maxsize: int) -> None:
        self.queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=maxsize)
        self.attached = True

    async def publish(self, event: str, payload: Any) -> None:
        """向仍连接的 subscriber 发布一个应用级事件。"""

        if self.attached:
            await self.queue.put((event, payload))


class CompletionSubscriber:
    """HTTP SSE 响应持有的轻量订阅句柄。

    句柄只暴露接收和解除订阅能力，Graph task 的所有权始终归 registry，防止请求
    取消传播到后台生成任务。
    """

    def __init__(self, channel: _CompletionChannel) -> None:
        self._channel = channel

    async def receive(self) -> tuple[str, Any]:
        """等待并返回下一个 ``(事件名, payload)``。"""

        return await self._channel.queue.get()

    def detach(self) -> None:
        """解除当前连接的订阅，不取消正在运行的 completion。"""

        self._channel.attached = False

    @property
    def pending_count(self) -> int:
        """返回尚未被 SSE 响应消费的事件数，主要用于运行状态观测。"""

        return self._channel.queue.qsize()


class CompletionProducerRegistry:
    """集中持有进程内 completion tasks，并协调应用关闭。

    registry 在 shutdown 开始后拒绝新任务，先给已有任务有限时间自然完成，再取消
    超时任务。它不提供任务恢复、并发配额或跨进程协调。
    """

    def __init__(self, *, shutdown_timeout: float = 30) -> None:
        self._shutdown_timeout = shutdown_timeout
        self._accepting = True
        self._tasks: set[asyncio.Task[None]] = set()

    def start(
        self,
        *,
        producer_factory: Callable[[Any], "CompletionProducer"],
        turn: AcceptedUserTurn,
        user_id: str,
    ) -> CompletionSubscriber:
        """创建 producer task，并返回供当前 HTTP 连接消费的 subscriber。"""

        if not self._accepting:
            raise RuntimeError("completion registry is shutting down")
        channel = _CompletionChannel(maxsize=16)
        subscriber = CompletionSubscriber(channel)
        producer = producer_factory(channel)
        task = asyncio.create_task(producer.run(turn=turn, user_id=user_id))
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return subscriber

    def _task_done(self, task: asyncio.Task[None]) -> None:
        """移除已结束任务，并显式读取异常以避免未检索异常告警。"""

        self._tasks.discard(task)
        if not task.cancelled():
            task.exception()

    async def shutdown(self) -> None:
        """停止接收新 completion，并在限时等待后清理剩余任务。"""

        # 步骤 1：先关闭入口，避免等待期间又注册新的后台任务。
        self._accepting = False
        if not self._tasks:
            return

        # 步骤 2：给进行中的 Graph 和 ASSISTANT 提交留出自然完成窗口。
        _, pending = await asyncio.wait(
            tuple(self._tasks),
            timeout=self._shutdown_timeout,
        )

        # 步骤 3：只取消超过关闭时限的任务，并收集取消结果完成资源收尾。
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    @property
    def active_count(self) -> int:
        """返回 registry 当前持有的未结束任务数。"""

        return len(self._tasks)


class CompletionProducer:
    """执行一次 metadata-first completion 并维护持久化终态。

    producer 先发布业务 ID，再把 Graph 输出投影为文本增量；只有完整 ASSISTANT 消息
    提交成功后才发布 ``completed``。Graph 或数据库任一阶段失败都统一发布 ``error``，
    且不会保存部分 ASSISTANT 内容或自动重试模型调用。
    """

    def __init__(
        self,
        *,
        graph: Any,
        model: Any,
        session_factory: Any,
        id_generator: Any,
        publisher: Any,
    ) -> None:
        self._graph = graph
        self._model = model
        self._session_factory = session_factory
        self._id_generator = id_generator
        self._publisher = publisher

    async def run(self, *, turn: AcceptedUserTurn, user_id: str) -> None:
        """运行已接受的用户轮次，并发布且仅发布一个终态事件。

        ``user_id`` 保留在运行接口中，用于明确 producer 属于哪个身份上下文；当前
        持久化依赖已在 USER 事务阶段完成所有权校验，因此这里不重复查询会话。
        """

        # 步骤 1：先发布 metadata，使调用方在模型运行前获得稳定业务 ID。
        await self._publisher.publish(
            "metadata",
            MetadataPayload(
                conversation_id=turn.conversation_id,
                user_message_id=turn.user_message_id,
            ),
        )

        try:
            # 步骤 2：消费 Graph 流并在内存中拼接最终回答；delta 可实时发给连接。
            answer = await self._accumulate_answer(turn)
            # 步骤 3：完整回答必须先提交业务表，completed 才能作为落库成功确认。
            assistant_message_id = await self._commit_assistant(turn, answer)
        except Exception:
            terminal_event = "error"
            terminal_payload = ErrorPayload(
                code="COMPLETION_FAILED",
                message="Completion failed",
                retryable=False,
            )
        else:
            terminal_event = "completed"
            terminal_payload = CompletedPayload(assistant_message_id=assistant_message_id)
        await self._publisher.publish(terminal_event, terminal_payload)

    async def _consume_graph_events(self, turn: AcceptedUserTurn):
        """运行指定会话的 Graph，并只 yield 应用认可的文本增量。

        conversation ID 的十进制字符串直接作为 LangGraph ``thread_id``，使 checkpoint
        与业务会话稳定对应；原始 LangGraph 事件不会越过本方法泄露给 transport。
        """

        async for event in self._graph.astream_events(
            {"messages": [HumanMessage(content=turn.content)]},
            {"configurable": {"thread_id": str(turn.conversation_id)}},
            context=ChatRuntimeContext(model=self._model),
            version="v2",
        ):
            delta = project_graph_event(event)
            if delta is not None:
                yield delta

    async def _accumulate_answer(self, turn: AcceptedUserTurn) -> str:
        """顺序转发文本增量，同时拼接最终需要持久化的完整回答。"""

        answer_parts: list[str] = []
        async for delta in self._consume_graph_events(turn):
            answer_parts.append(delta.content)
            await self._publisher.publish("content_delta", delta)
        return "".join(answer_parts)

    async def _commit_assistant(self, turn: AcceptedUserTurn, answer: str) -> int:
        """在独立业务事务中保存完整 ASSISTANT 消息并返回其 Snowflake ID。

        ASSISTANT 以本轮 USER 消息作为 parent。事务抛错时异常交由 ``run`` 转换为
        ``error``，因此调用方不会收到错误的 ``completed`` 确认。
        """

        assistant_message_id = self._id_generator.next_id()
        async with self._session_factory() as session:
            async with session.begin():
                MessageRepository(session).add_assistant(
                    message_id=assistant_message_id,
                    conversation_id=turn.conversation_id,
                    parent_message_id=turn.user_message_id,
                    content=answer,
                )
        return assistant_message_id
