from fastapi import APIRouter, status

from app.common.response import APIResponse, success_response
from app.core.exceptions import AppException
from app.modules.chat.schemas import ChatRequest, ChatResponse
from app.modules.chat.service import chat as run_chat

router = APIRouter()


@router.post("", response_model=APIResponse[ChatResponse])
async def chat(request: ChatRequest) -> APIResponse[ChatResponse]:
    """处理单轮聊天请求。"""

    if not request.message.strip():
        raise AppException("message is required", status_code=status.HTTP_400_BAD_REQUEST)

    answer = await run_chat(request.message)
    return success_response(ChatResponse(answer=answer))
