from fastapi import APIRouter

from app.common.response import APIResponse, success_response

router = APIRouter()

# 仅占位，开发暂不考虑该模块
@router.get("/health", response_model=APIResponse[dict[str, str]])
async def auth_health() -> APIResponse[dict[str, str]]:
    """返回认证模块占位健康状态。"""

    return success_response({"status": "ok"})

