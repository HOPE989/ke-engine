"""Chat completion 的后台执行与实时订阅协调。

本模块位于 HTTP transport 与 LangGraph/数据库之间，负责一次 completion 从开始执行
到发布终态的完整生命周期。它刻意把 Graph 后台任务与 HTTP 请求协程分开：

1. Router 调用 ``CompletionProducerRegistry.start()`` 注册后台任务。
2. Registry 为本次请求创建唯一的 ``_CompletionChannel``。
3. 同一个 Channel 一端交给 ``CompletionProducer`` 发布事件，另一端包装成
   ``CompletionSubscriber`` 供 Router 消费。
4. Producer 在 Registry 持有的 asyncio task 中运行，顺序发布 metadata、文本增量和
   completed/error 终态，并负责保存完整 ASSISTANT 消息。
5. Router 只把 Subscriber 收到的事件转换成 SSE；客户端断开时只解除订阅，不取消
   Registry 持有的 Producer task。

可以把核心关系理解成：

    CompletionProducer --publish()--> _CompletionChannel.queue
                                          |
                                          v
    HTTP SSE response <--receive()-- CompletionSubscriber

这里的 Channel 是当前 Python 进程中的临时异步队列，不是 Kafka、Redis 等跨进程消息
中间件，也不负责事件重放。进程退出后，队列中的事件不会保留。
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.contracts.chat import (
    CompletionFinishReason,
    CompletedPayload,
    ContentDeltaPayload,
    ErrorPayload,
    MetadataPayload,
)
from app.domains.chat.graph import ChatRuntimeContext
from app.domains.chat.graph.business_understanding import (
    ClarificationInterruptPayload,
)
from app.domains.chat.graph.routing import CLARIFY_NODE, LLM_NODE
from app.domains.chat.repositories import MessageRepository
from app.domains.chat.services.conversation import AcceptedUserTurn
from app.services.chat_api.streaming import (
    project_clarification_interrupt,
    project_graph_event,
)


@dataclass(frozen=True, slots=True)
class GraphCompletion:
    """Graph 本轮可持久化内容及其成功终止原因。"""

    content: str
    finish_reason: CompletionFinishReason


async def resolve_graph_input(
    graph: Any,
    config: dict[str, Any],
    content: str,
) -> dict[str, list[HumanMessage]] | Command:
    """把普通新轮次与唯一受支持的澄清恢复严格分流。"""

    snapshot = await graph.aget_state(config)
    if snapshot.next == () and snapshot.tasks == ():
        return {"messages": [HumanMessage(content=content)]}
    if snapshot.next != (CLARIFY_NODE,) or len(snapshot.tasks) != 1:
        raise ValueError("unsupported pending graph state")

    task = snapshot.tasks[0]
    if task.name != CLARIFY_NODE or len(task.interrupts) != 1:
        raise ValueError("unsupported pending graph task")
    ClarificationInterruptPayload.model_validate(task.interrupts[0].value)
    return Command(resume=content)


class _CompletionChannel:
    """单次 completion 的进程内事件通道。

    Registry 每次调用 ``start()`` 都会新建一个 Channel。Producer 和 Subscriber 保存的
    是同一个 Channel 对象：Producer 调用本对象的 ``publish()`` 写入队列，Subscriber
    调用 ``queue.get()`` 从同一个队列读取，因此不需要额外的事件转发器。

    Channel 只服务当前 HTTP 连接，不承担跨进程传输或断线重放。Subscriber detach 后，
    ``attached`` 变为 False，待发事件会被清空，``publish()`` 会跳过后续事件并从已阻塞
    的背压等待中恢复。这个状态不会反向取消 Producer，Producer 仍会生成完整回答并落库。
    """

    def __init__(self, *, maxsize: int) -> None:
        # 有界队列提供简单的背压：连接仍存在时，如果 Producer 连续发布过快，
        # queue.put() 会等待 Router 消费已有事件，避免队列无限增长。
        self.queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=maxsize)
        # attached 描述的是“是否仍有实时 SSE 消费者”，不是 Producer 的运行状态。
        self.attached = True

    async def publish(self, event: str, payload: Any) -> None:
        """向仍连接的 Subscriber 发布一个应用级事件。

        ``await queue.put(...)`` 只负责把事件交给同进程队列。事件如何编码成 SSE、如何
        写入网络响应，是 Router 的职责。
        """

        if self.attached:
            await self.queue.put((event, payload))
            if not self.attached:
                self._discard_pending()

    def detach(self) -> None:
        """解除订阅、丢弃待发事件，并唤醒可能阻塞于背压的 Publisher。"""

        self.attached = False
        self._discard_pending()

    def _discard_pending(self) -> None:
        """同步清空当前队列；每次 get 同时唤醒一个等待 queue.put 的协程。"""

        while True:
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                return


class CompletionSubscriber:
    """HTTP SSE 响应持有的轻量订阅句柄。

    Registry 使用 Channel 创建 Subscriber 后把它返回给 Router。这个对象只有“读取事件”
    和“解除实时订阅”两种能力，既拿不到 Producer，也拿不到 asyncio task。

    Graph task 的所有权始终归 Registry。这样 HTTP 请求协程被取消时，不会因为持有或
    await Graph task 而把取消传播给后台生成任务。
    """

    def __init__(self, channel: _CompletionChannel) -> None:
        self._channel = channel

    async def receive(self) -> tuple[str, Any]:
        """等待并返回下一个 ``(事件名, payload)``。

        队列为空时会挂起当前 SSE 生成器，但不会阻塞事件循环；Producer 发布新事件后，
        等待会被唤醒。
        """

        return await self._channel.queue.get()

    def detach(self) -> None:
        """解除当前连接的实时订阅，不取消正在运行的 completion。

        Router 在 SSE 正常结束、客户端断开或响应异常时都会调用此方法。它只解除共享
        Channel 的实时交付并清空待发事件；后台 task 不在 Subscriber 中，因此不会被取消。
        """

        self._channel.detach()

    @property
    def pending_count(self) -> int:
        """返回尚未被 SSE 响应消费的事件数，主要用于运行状态观测。"""

        return self._channel.queue.qsize()


class CompletionProducerRegistry:
    """集中持有进程内 completion tasks，并协调应用关闭。

    Registry 在 FastAPI lifespan 中创建，并由整个应用实例共享。它是真正拥有后台
    asyncio task 的对象：Router 只获得 Subscriber，不直接持有 task。

    Registry 在 shutdown 开始后拒绝新任务，先给已有任务有限时间自然完成，再取消
    超时任务。它不提供任务恢复、并发配额或跨进程协调；多进程部署时，每个进程都有
    自己独立的 Registry。
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
        """创建 Producer task，并返回供当前 HTTP 连接消费的 Subscriber。

        ``producer_factory`` 之所以接收一个参数，是因为 Channel 必须先由 Registry 创建。
        Router 传入的 lambda 只是一个延迟创建 Producer 的工厂。例如：

        ``producer_factory=lambda publisher: CompletionProducer(publisher=publisher, ...)``

        当下方执行 ``producer_factory(channel)`` 时，Python 按位置参数传递规则，把这里的
        ``channel`` 赋给 lambda 的形参 ``publisher``。所以 publisher 并非自动注入，它就是
        Registry 主动传入的同一个 ``_CompletionChannel`` 对象。
        """

        if not self._accepting:
            raise RuntimeError("completion registry is shutting down")
        # 第一步：为本次 completion 创建独立事件通道。不同请求不会共用队列。
        channel = _CompletionChannel(maxsize=16)
        # 第二步：Subscriber 保存 channel，稍后由 Router 从 channel.queue 读取事件。
        subscriber = CompletionSubscriber(channel)
        # 第三步：把同一个 channel 作为位置参数交给 Router 提供的工厂。
        # 在 Router 的 lambda 中，这个实参对应名为 publisher 的形参；Producer 随后会
        # 通过 publisher.publish() 把事件写回上面 Subscriber 所读取的同一个队列。
        producer = producer_factory(channel)
        # 第四步：把 Producer 放入独立 task。start() 不等待 run() 完成，而是立即把
        # Subscriber 返回给 Router，使 HTTP 响应可以一边等待事件、一边实时发送 SSE。
        task = asyncio.create_task(producer.run(turn=turn, user_id=user_id))
        # 保存强引用既明确了 task 的所有权，也让 shutdown() 能统一等待或取消它们。
        self._tasks.add(task)
        # task 结束时自动从集合移除，避免已经完成的任务长期滞留。
        task.add_done_callback(self._task_done)
        return subscriber

    def _task_done(self, task: asyncio.Task[None]) -> None:
        """移除已结束任务，并显式读取异常以避免未检索异常告警。"""

        self._tasks.discard(task)
        if not task.cancelled():
            # 即使调用方不 await 后台 task，也必须读取其异常，否则 asyncio 会报告
            # “Task exception was never retrieved”。Producer 正常业务错误通常已在 run()
            # 内转成 error 事件；这里处理的是逃逸出 run() 的意外异常。
            task.exception()

    async def shutdown(self) -> None:
        """停止接收新 completion，并在限时等待后清理剩余任务。

        该方法由 FastAPI lifespan 的清理栈调用。先封闭入口再等待已有任务，可以避免
        shutdown 等待期间又注册出无法管理的新任务。
        """

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

    每个实例只处理一个已接受的用户轮次。Producer 先发布业务 ID，再把 Graph 输出投影
    为文本增量；只有完整 ASSISTANT 消息提交成功后才发布 ``completed``。

    ``publisher`` 在生产环境中实际是 Registry 创建的 ``_CompletionChannel``，使用 Any
    是为了让测试可以注入只实现 ``publish(event, payload)`` 的 FakePublisher。

    Graph 或数据库任一阶段失败都统一发布 ``error``，且不会保存部分 ASSISTANT 内容或
    自动重试模型调用。Producer 不负责把事件编码成 SSE，那是 Router/streaming 层的职责。
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

        ``user_id`` 保留在运行接口中，用于明确 Producer 属于哪个身份上下文；当前
        持久化依赖已在 USER 事务阶段完成所有权校验，因此这里不重复查询会话。

        正常情况下事件顺序为 ``metadata -> content_delta* -> completed``；失败情况下为
        ``metadata -> content_delta* -> error``。无论成功失败，都只发布一个终态事件。
        """

        # 步骤 1：先发布 metadata。此时 USER 消息已经在 Router 前置事务中提交，所以
        # conversation_id 和 user_message_id 都是稳定、可立即交给客户端的业务 ID。
        await self._publisher.publish(
            "metadata",
            MetadataPayload(
                conversation_id=turn.conversation_id,
                user_message_id=turn.user_message_id,
            ),
        )

        try:
            # 步骤 2：消费 Graph 流并在内存中拼接最终回答；每个 delta 同时实时发布。
            completion = await self._consume_graph_events(turn)
            # 步骤 3：完整回答必须先提交业务表。completed 的语义不是“模型流结束”，
            # 而是“模型流结束且 ASSISTANT 消息已经成功落库”。
            assistant_message_id = await self._commit_assistant(turn, completion.content)
        except Exception:
            # 不把原始异常文本发送给客户端，避免数据库地址、密钥或内部栈信息泄露。
            # 已经发出的 delta 无法收回，但失败时不会保存不完整的 ASSISTANT 消息。
            terminal_event = "error"
            terminal_payload = ErrorPayload(
                code="COMPLETION_FAILED",
                message="Completion failed",
                retryable=False,
            )
        else:
            terminal_event = "completed"
            terminal_payload = CompletedPayload(
                assistant_message_id=assistant_message_id,
                finish_reason=completion.finish_reason,
            )
        # try/except/else 统一汇合到此处，保证业务错误只产生一个终态事件。
        await self._publisher.publish(terminal_event, terminal_payload)

    async def _consume_graph_events(self, turn: AcceptedUserTurn) -> GraphCompletion:
        """运行指定会话的 Graph，发布公开增量并收集可持久化结果。

        Conversation ID 的十进制字符串直接作为 LangGraph ``thread_id``，使同一业务
        会话的多轮调用稳定落到同一份 checkpoint；原始 LangGraph 事件不会越过本方法
        泄露给 transport。Graph 正常到达 END 时返回普通回答；受支持澄清中断则立即
        发布公开问题并返回中断结果。
        """

        answer_parts: list[str] = []
        config = {"configurable": {"thread_id": str(turn.conversation_id)}}
        graph_input = await resolve_graph_input(self._graph, config, turn.content)
        # astream_events() 是异步迭代器：Graph 每产生一个事件就进入循环，不必等待整段
        # 回答完成。普通轮次使用 HumanMessage；挂起澄清使用同 thread 的 Command resume。
        async for event in self._graph.astream_events(
            graph_input,
            config,
            context=ChatRuntimeContext(model=self._model),
            version="v2",
        ):
            # Graph 会产生节点、链、模型等多类底层事件。这里只保留 API 协议认可的文本
            # 增量，并转换成稳定的应用层 payload，避免 transport 依赖 LangGraph 内部格式。
            metadata = event.get("metadata")
            delta = (
                project_graph_event(event)
                if isinstance(metadata, dict)
                and metadata.get("langgraph_node") == LLM_NODE
                else None
            )
            if delta is not None:
                answer_parts.append(delta.content)
                await self._publisher.publish("content_delta", delta)

            clarification = project_clarification_interrupt(event)
            if clarification is not None:
                question_delta = ContentDeltaPayload(content=clarification.question)
                await self._publisher.publish("content_delta", question_delta)
                return GraphCompletion(
                    content=clarification.question,
                    finish_reason="interrupt",
                )

        return GraphCompletion(content="".join(answer_parts), finish_reason="stop")

    async def _commit_assistant(self, turn: AcceptedUserTurn, answer: str) -> int:
        """在独立业务事务中保存完整 ASSISTANT 消息并返回其 Snowflake ID。

        ASSISTANT 以本轮 USER 消息作为 parent，从而在业务消息表中保留本轮问答关系。
        这里使用独立事务，是因为接收 USER 消息的前置事务早已在 Router 中完成并提交。
        事务抛错时异常交由 ``run`` 转换为 ``error``，因此调用方不会收到错误的
        ``completed`` 确认。
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
