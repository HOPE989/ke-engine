"""Chat completion、会话列表和消息历史的 HTTP transport 层。

路由只处理身份、输入转换、领域错误映射与响应编码。业务事务由领域 service 管理，
Graph 的执行与终态持久化由后台 producer 管理。
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

    USER 消息提交失败时不会创建 producer 或返回成功流；会话不存在和不属于当前
    用户统一映射为 404，避免通过响应差异泄露资源所有权。
    """

    # 步骤 1：先在业务事务中创建/校验会话并提交 USER 消息。
    try:
        turn = await ConversationService(
            chat_deps.session_factory,
            chat_deps.id_generator,
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

    # 步骤 2：业务事务成功后才注册后台 producer；请求协程不直接拥有 Graph task。
    subscriber = chat_deps.producer_registry.start(
        producer_factory=lambda publisher: CompletionProducer(
            graph=chat_deps.graph,
            model=chat_deps.model,
            session_factory=chat_deps.session_factory,
            id_generator=chat_deps.id_generator,
            publisher=publisher,
        ),
        turn=turn,
        user_id=principal.user_id,
    )

    async def event_stream():
        """转发当前连接的实时事件，并在终态或断连时解除订阅。"""

        try:
            while True:
                event, payload = await subscriber.receive()
                yield encode_sse(event, payload)
                if event in {"completed", "error"}:
                    break
        finally:
            # detach 只停止向本连接入队，producer 仍继续生成并持久化完整回答。
            subscriber.detach()

    # 步骤 3：返回禁缓存、禁代理缓冲的 SSE 响应，确保 token 可以及时到达客户端。
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
