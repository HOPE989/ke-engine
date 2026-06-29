from fastapi import APIRouter

from app.common.response import APIResponse, success_response
from app.modules.orders.schemas import OrderRead

router = APIRouter()


@router.get("/", response_model=APIResponse[list[OrderRead]])
async def list_orders() -> APIResponse[list[OrderRead]]:
    return success_response([])

