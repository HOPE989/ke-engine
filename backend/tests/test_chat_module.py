from fastapi import APIRouter


def test_chat_module_exposes_function_style_components():
    from app.contracts.agent.http import ChatRequest, ChatResponse
    from app.services.agent_api.chat_router import router
    from app.domains.agent.services import chat as chat_service

    assert router
    assert isinstance(router, APIRouter)
    assert ChatRequest.model_fields["message"]
    assert ChatResponse.model_fields["answer"]
    assert callable(chat_service.chat)
    assert not hasattr(chat_service, "ChatService")
