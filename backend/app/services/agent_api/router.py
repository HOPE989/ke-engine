"""Agent API 聚合路由。"""

from fastapi import APIRouter

from app.services.agent_api.chat_router import router as chat_router

router = APIRouter()
router.include_router(chat_router, prefix="/chat", tags=["chat"])
