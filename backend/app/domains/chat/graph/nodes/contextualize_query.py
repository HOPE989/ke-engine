from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from pydantic import ValidationError

from app.domains.chat.graph.business_understanding import (
    BusinessUnderstandingResult,
)
from app.domains.chat.graph.context import ChatRuntimeContext
from app.domains.chat.graph.query_contextualization import (
    QueryContextInput,
    QueryContextResult,
    QueryContextUpdate,
)
from app.domains.chat.graph.query_contextualization.prompt import (
    build_query_contextualization_messages,
)
from app.domains.chat.graph.state import ChatState


async def contextualize_query_node(
    state: ChatState,
    runtime: Runtime[ChatRuntimeContext],
    config: RunnableConfig | None = None,
) -> QueryContextUpdate:
    return await invoke_contextualize_query(
        state,
        model=runtime.context.model,
        config=config,
    )


async def invoke_contextualize_query(
    state: ChatState,
    *,
    model: BaseChatModel,
    config: RunnableConfig | None = None,
) -> QueryContextUpdate:
    messages = state["messages"]
    current_index = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if isinstance(messages[index], HumanMessage)
        ),
        None,
    )
    if current_index is None:
        raise ValueError("query contextualization requires a user message")
    current = messages[current_index]
    if not isinstance(current.content, str) or not current.content.strip():
        raise ValueError("query contextualization requires text user content")

    raw_understanding = state["business_understanding"]
    understanding = BusinessUnderstandingResult.model_validate(
        raw_understanding.model_dump()
        if hasattr(raw_understanding, "model_dump")
        else raw_understanding
    )
    history = [
        {
            "role": "user" if isinstance(message, HumanMessage) else "assistant",
            "content": message.content,
        }
        for message in messages[:current_index]
        if isinstance(message, (HumanMessage, AIMessage))
        and isinstance(message.content, str)
        and message.content.strip()
    ][-10:]
    entities = {
        key: value
        for key, value in understanding.entities.model_dump().items()
        if isinstance(value, str) and value.strip()
    }
    request = QueryContextInput.model_validate(
        {
            "original_query": current.content,
            "conversation_context": history,
            "business_context": {
                "intent": (
                    understanding.intent.value
                    if understanding.intent is not None
                    else None
                ),
                "entities": entities,
            },
        }
    )
    try:
        structured_model = model.with_structured_output(
            QueryContextResult,
            method="json_mode",
        )
        raw_result = await structured_model.ainvoke(
            build_query_contextualization_messages(request),
            config=config,
        )
        result = QueryContextResult.model_validate(raw_result)
    except ValidationError:
        return {"standalone_query": request.original_query}
    except Exception:
        return {"standalone_query": request.original_query}
    return {"standalone_query": result.standalone_query}
