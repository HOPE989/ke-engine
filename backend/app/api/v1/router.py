from fastapi import APIRouter

from app.modules.auth.router import router as auth_router
from app.modules.chat.router import router as chat_router
from app.modules.orders.router import router as orders_router
from app.modules.users.router import router as users_router

api_router = APIRouter()
# 仅占位，开发暂不考虑该模块
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(chat_router, prefix="/chat", tags=["chat"])
# 仅占位，开发暂不考虑该模块
api_router.include_router(users_router, prefix="/users", tags=["users"])
# 仅占位，开发暂不考虑该模块
api_router.include_router(orders_router, prefix="/orders", tags=["orders"])
