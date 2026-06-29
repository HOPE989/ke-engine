from fastapi import APIRouter

from app.common.response import APIResponse, success_response

router = APIRouter()


@router.get("/health", response_model=APIResponse[dict[str, str]])
async def auth_health() -> APIResponse[dict[str, str]]:
    return success_response({"status": "ok"})

