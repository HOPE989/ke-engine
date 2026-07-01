from fastapi import APIRouter

from app.common.response import APIResponse, success_response
from app.modules.orders.schemas import OrderRead

router = APIRouter()

# 仅占位，开发暂不考虑该模块
@router.get("/", response_model=APIResponse[list[OrderRead]])
async def list_orders() -> APIResponse[list[OrderRead]]:
    """返回订单模块占位列表。"""

    return success_response([])

