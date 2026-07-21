"""Chat completion、会话列表和消息历史的 HTTP transport 层。

路由只处理身份、输入转换、领域错误映射与响应编码。业务事务由领域 Service 管理，
Graph 的执行与终态持久化由后台 Producer 管理。

对于流式 completion，本文件和 ``domains.chat.services.runtime`` 的分工如下：

1. Router 先同步于请求生命周期完成身份校验和 USER 消息事务。
2. Router 向 Registry 提交一个 Producer 工厂；Registry 创建 Channel 后才调用该工厂。
3. Registry 在独立 asyncio task 中运行 Producer，并向 Router 返回 Subscriber。
4. Router 从 Subscriber 读取应用事件，将其编码成 SSE 后写入 HTTP 响应。
5. HTTP 连接结束时 Router 只 detach Subscriber；Producer 继续完成生成和落库。

这种划分保证“客户端是否保持连接”和“已接受的用户轮次是否完整执行”互不绑定。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from starlette.responses import StreamingResponse

from app.common.response import APIResponse, success_response
from app.contracts.chat.http import (
    CompletionRequest,
    ConversationPage,
    ConversationSummary,
    MessagePage,
    MessageSummary,
)
from app.core.exceptions import AppException
from app.domains.chat.repositories import ConversationRepository, MessageRepository
from app.domains.chat.services.completion_lock import (
    ConversationBusy,
    ConversationLockUnavailable,
    release_completion_lock,
)
from app.domains.chat.services.conversation import ConversationNotFound, ConversationService
from app.domains.chat.services.runtime import CompletionProducer
from app.identity import Principal, get_current_principal
from app.services.chat_api.deps import ChatApiDeps, get_chat_deps
from app.services.chat_api.streaming import encode_sse

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/completions")
async def create_completion(
    request: CompletionRequest,
    principal: Annotated[Principal, Depends(get_current_principal)],
    chat_deps: Annotated[ChatApiDeps, Depends(get_chat_deps)],
) -> StreamingResponse:
    """接受一轮用户输入并返回 metadata-first 的实时 SSE 流。

    FastAPI 会分别从请求体、认证依赖和应用 lifespan 中准备 request、principal 与
    chat_deps。USER 消息提交失败时不会创建 Producer 或返回成功流；会话不存在和不属于当前
    用户统一映射为 404，避免通过响应差异泄露资源所有权。

    此函数不会直接执行或 await LangGraph。它只注册后台 Producer，然后消费与当前 HTTP
    连接对应的 Subscriber。
    """

    # 步骤 1：先在业务事务中创建/校验会话并提交 USER 消息。
    # 这一步在启动后台任务之前完成，因此只要进入流式响应，metadata 中引用的会话和
    # USER 消息就一定已经落库。反过来，前置事务失败时不会产生孤立的后台任务。
    try:
        accepted = await ConversationService(
            chat_deps.session_factory,
            chat_deps.id_generator,
            chat_deps.title_model,
            completion_lock_factory=chat_deps.completion_lock_factory,
        ).accept_user_turn(
            user_id=principal.user_id,
            content=request.content,
            conversation_id=(
                int(request.conversation_id)
                if request.conversation_id is not None
                else None
            ),
        )
    except ConversationNotFound as exc:
        raise AppException("conversation not found", status.HTTP_404_NOT_FOUND) from exc
    except ConversationBusy as exc:
        raise AppException("conversation busy", status.HTTP_409_CONFLICT) from exc
    except ConversationLockUnavailable as exc:
        raise AppException(
            "conversation lock unavailable",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc

    # 步骤 2：业务事务成功后才注册后台 Producer；请求协程不直接拥有 Graph task。
    #
    # 这里传入的是“如何创建 Producer”的工厂，而不是已经创建好的 Producer。原因是
    # publisher/Channel 由 Registry.start() 内部创建，Router 在调用 start() 之前拿不到它。
    # Registry 内部实际执行：
    #
    #     channel = _CompletionChannel(...)
    #     subscriber = CompletionSubscriber(channel)
    #     producer = producer_factory(channel)
    #
    # 最后一行调用下面的 lambda 时，Python 按位置参数规则把 channel 赋给 lambda 的
    # 第一个形参 publisher。因此 publisher 并不是 FastAPI 注入或从外层捕获的变量，
    # 它就是 Registry 主动传入的 channel；随后又被保存到 CompletionProducer 中。
    try:
        subscriber = chat_deps.producer_registry.start(
            producer_factory=lambda publisher: CompletionProducer(
                graph=chat_deps.graph,
                model=chat_deps.model,
                session_factory=chat_deps.session_factory,
                id_generator=chat_deps.id_generator,
                publisher=publisher,
            ),
            turn=accepted.turn,
            completion_lock=accepted.lock,
            user_id=principal.user_id,
        )
    except BaseException:
        # Registry.start() 返回后锁的所有权才转移给后台 task；此前失败由请求侧释放。
        await release_completion_lock(accepted.lock)
        raise

    async def event_stream():
        """转发当前连接的实时事件，并在终态或断连时解除订阅。

        StreamingResponse 会异步迭代这个生成器。队列暂时没有事件时，receive() 会异步
        等待；Producer 发布事件后恢复执行并 yield 一段已经编码好的 SSE 数据。
        """

        try:
            while True:
                # Subscriber 与 Producer 引用同一个 Channel：Producer 的 publish() 写入
                # channel.queue，这里的 receive() 从该队列取出同一个 (event, payload)。
                event, payload = await subscriber.receive()
                yield encode_sse(event, payload)
                # completed/error 都是唯一终态。终态已经发送后无需继续等待新事件。
                if event in {"completed", "error"}:
                    break
        finally:
            # async generator 正常结束、客户端中途断开或发送响应时发生异常，都会执行
            # finally。detach 只让 Channel 停止为本连接入队，不会取消 Registry 持有的
            # Producer task；即使客户端断开，Producer 仍继续生成并持久化完整回答。
            subscriber.detach()

    # 步骤 3：构造响应并把 event_stream() 交给 Starlette 异步消费。此处返回响应对象时，
    # 后台 Producer 通常仍在运行；后续 token 通过生成器逐条写给客户端。
    # 禁缓存、禁代理缓冲可以避免中间层攒满一批数据后才发送，确保 token 及时到达。
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations", response_model=APIResponse[ConversationPage])
async def list_conversations(
    principal: Annotated[Principal, Depends(get_current_principal)],
    chat_deps: Annotated[ChatApiDeps, Depends(get_chat_deps)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
) -> APIResponse[ConversationPage]:
    """按更新时间倒序列出当前用户拥有的会话，不读取 checkpoint state。"""

    async with chat_deps.session_factory() as session:
        items, next_cursor = await ConversationRepository(session).list_owned(
            user_id=principal.user_id,
            limit=limit,
            cursor=cursor,
        )
    return success_response(
        ConversationPage(
            items=[
                ConversationSummary(
                    id=item.id,
                    title=item.title,
                    status=item.status,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                )
                for item in items
            ],
            next_cursor=next_cursor,
        )
    )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=APIResponse[MessagePage],
)
async def list_messages(
    conversation_id: int,
    principal: Annotated[Principal, Depends(get_current_principal)],
    chat_deps: Annotated[ChatApiDeps, Depends(get_chat_deps)],
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    cursor: str | None = None,
) -> APIResponse[MessagePage]:
    """按时间正序返回当前用户指定会话的业务消息历史。

    查询前再次校验会话所有权；missing 和 foreign-owned conversation 使用相同 404。
    """

    async with chat_deps.session_factory() as session:
        conversation = await ConversationRepository(session).get_owned(
            conversation_id=conversation_id,
            user_id=principal.user_id,
        )
        if conversation is None:
            raise AppException("conversation not found", status.HTTP_404_NOT_FOUND)
        items, next_cursor = await MessageRepository(session).list_owned(
            user_id=principal.user_id,
            conversation_id=conversation_id,
            limit=limit,
            cursor=cursor,
        )
    return success_response(
        MessagePage(
            items=[
                MessageSummary(
                    id=item.id,
                    conversation_id=item.conversation_id,
                    parent_message_id=item.parent_message_id,
                    role=item.role,
                    content=item.content,
                    created_at=item.created_at,
                )
                for item in items
            ],
            next_cursor=next_cursor,
        )
    )
