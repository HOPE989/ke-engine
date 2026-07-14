"""Chat 会话与消息 HTTP 查询。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.common.response import APIResponse, success_response
from app.contracts.chat.http import (
    ConversationPage,
    ConversationSummary,
    MessagePage,
    MessageSummary,
)
from app.core.exceptions import AppException
from app.domains.chat.repositories import ConversationRepository, MessageRepository
from app.identity import Principal, get_current_principal
from app.services.chat_api.deps import ChatApiDeps, get_chat_deps

router = APIRouter(prefix="/chat", tags=["chat"])


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
