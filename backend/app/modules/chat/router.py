from fastapi import APIRouter, status

from app.common.response import APIResponse, success_response
from app.core.exceptions import AppException
from app.modules.chat.schemas import ChatRequest, ChatResponse
from app.modules.chat.service import ChatService

router = APIRouter()


@router.post("", response_model=APIResponse[ChatResponse])
async def chat(request: ChatRequest) -> APIResponse[ChatResponse]:
    if not request.message.strip():
        raise AppException("message is required", status_code=status.HTTP_400_BAD_REQUEST)

    answer = await ChatService().chat(request.message)
    return success_response(ChatResponse(answer=answer))
