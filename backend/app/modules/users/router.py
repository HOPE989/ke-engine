from fastapi import APIRouter

from app.common.response import APIResponse, success_response
from app.modules.users.schemas import UserRead

router = APIRouter()

# 仅占位，开发暂不考虑该模块
@router.get("/", response_model=APIResponse[list[UserRead]])
async def list_users() -> APIResponse[list[UserRead]]:
    return success_response([])

