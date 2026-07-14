"""Chat 会话与消息 HTTP 查询。"""

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
        try:
            while True:
                event, payload = await subscriber.receive()
                yield encode_sse(event, payload)
                if event in {"completed", "error"}:
                    break
        finally:
            subscriber.detach()

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
