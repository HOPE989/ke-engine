def test_agent_domain_exposes_chat_service_import_paths():
    from app.contracts.agent.http import ChatRequest, ChatResponse
    from app.domains.agent.services.chat import chat, get_chat_model
    from app.services.agent_api.chat_router import router

    assert callable(chat)
    assert callable(get_chat_model)
    assert ChatRequest.model_fields["message"]
    assert ChatResponse.model_fields["answer"]
    assert router
