from fastapi import APIRouter

from app.common.response import APIResponse, success_response
from app.modules.users.schemas import UserRead

router = APIRouter()


@router.get("/", response_model=APIResponse[list[UserRead]])
async def list_users() -> APIResponse[list[UserRead]]:
    return success_response([])

