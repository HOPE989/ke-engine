from fastapi import APIRouter


def test_chat_module_exposes_function_style_components():
    from app.modules.chat.router import router
    from app.modules.chat.schemas import ChatRequest, ChatResponse
    from app.modules.chat import service as chat_service

    assert router
    assert isinstance(router, APIRouter)
    assert ChatRequest.model_fields["message"]
    assert ChatResponse.model_fields["answer"]
    assert callable(chat_service.chat)
    assert not hasattr(chat_service, "ChatService")
