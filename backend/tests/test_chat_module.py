from fastapi import APIRouter


def test_chat_module_exposes_minimal_components():
    from app.modules.chat.router import router
    from app.modules.chat.schemas import ChatRequest, ChatResponse
    from app.modules.chat.service import ChatService

    assert router
    assert isinstance(router, APIRouter)
    assert ChatRequest.model_fields["message"]
    assert ChatResponse.model_fields["answer"]
    assert ChatService
