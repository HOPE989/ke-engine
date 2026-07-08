"""Document API 聚合路由。"""

from fastapi import APIRouter

from app.services.document_api.document_router import router as document_router

router = APIRouter()
router.include_router(document_router, prefix="/document", tags=["document"])
