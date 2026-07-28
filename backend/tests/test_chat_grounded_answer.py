import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime


class RecordingModel:
    def __init__(self, response="依据规程，应按规定编组。[1]"):
        self.response = response
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return AIMessage(content=self.response)


def _state(items):
    from app.domains.rag.services import EvidencePackage

    package = EvidencePackage(
        query="超限货物列车编组要求",
        selected_retrievers=("DOCUMENT_HYBRID",),
        evidence_items=items,
    )
    return {
        "messages": [HumanMessage(content="如何编组？")],
        "business_understanding": {
            "reasoning": "运输知识问题",
            "route": "BUSINESS",
            "intent": "TRANSPORT_OPERATION_QA",
            "entities": {},
        },
        "evidence_package": package.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
        ),
    }


@pytest.mark.asyncio
async def test_grounded_answer_numbers_evidence_and_requires_citations():
    from app.domains.chat.graph.context import ChatRuntimeContext
    from app.domains.chat.graph.nodes.grounded_answer import (
        GROUNDED_ANSWER_SYSTEM_PROMPT,
        grounded_answer_node,
    )
    from app.domains.rag.services import EvidenceItem

    model = RecordingModel()
    items = (
        EvidenceItem(
            citation_id="doc-1:chunk-1",
            content="超限货物列车应按规定编组。",
            doc_id="doc-1",
            chunk_id="chunk-1",
        ),
        EvidenceItem(
            citation_id="doc-2:chunk-3",
            content="编组后应进行复核。",
            doc_id="doc-2",
            chunk_id="chunk-3",
        ),
    )

    update = await grounded_answer_node(
        _state(items),
        Runtime(context=ChatRuntimeContext(model=model)),
    )

    assert update["messages"][0].content.endswith("[1]")
    prompt = model.calls[0]
    assert "只能使用" in GROUNDED_ANSWER_SYSTEM_PROMPT
    assert "[1]" in prompt[1].content
    assert "[2]" in prompt[1].content
    assert "超限货物列车应按规定编组。" in prompt[1].content


@pytest.mark.asyncio
async def test_grounded_answer_returns_fixed_text_without_calling_model():
    from app.domains.chat.graph.context import ChatRuntimeContext
    from app.domains.chat.graph.nodes.grounded_answer import (
        EMPTY_EVIDENCE_ANSWER,
        grounded_answer_node,
    )

    model = RecordingModel()

    update = await grounded_answer_node(
        _state(()),
        Runtime(context=ChatRuntimeContext(model=model)),
    )

    assert update["messages"][0].content == EMPTY_EVIDENCE_ANSWER
    assert model.calls == []
