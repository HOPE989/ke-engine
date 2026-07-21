import asyncio
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from pydantic import Field, PrivateAttr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.domains.chat.graph.business_understanding import BusinessUnderstandingResult

DATABASE_URL = "postgresql+asyncpg://ke_engine:ke_engine@127.0.0.1:5432/ke_engine"


def unique_thread_id() -> str:
    return uuid4().hex


def non_business_result() -> BusinessUnderstandingResult:
    return BusinessUnderstandingResult.model_validate(
        {
            "reasoning": "integration fake routes ordinary chat",
            "route": "NON_BUSINESS",
            "intent": None,
            "entities": {},
            "clarification_question": None,
        }
    )


class ScriptedStructuredRunnable:
    def __init__(self, outputs: list[BusinessUnderstandingResult]):
        self.outputs = list(outputs)
        self.calls: list[list[object]] = []

    async def ainvoke(self, messages):
        self.calls.append(list(messages))
        if not self.outputs:
            raise AssertionError("no scripted structured output remains")
        return self.outputs.pop(0)


class ScriptedChatModel(FakeListChatModel):
    """同时提供 structured 决策和真实 chat-model stream provenance 的离线模型。"""

    structured_schemas: list[type[BusinessUnderstandingResult]] = Field(
        default_factory=list
    )
    ordinary_calls: list[list[object]] = Field(default_factory=list)
    _structured_runnable: ScriptedStructuredRunnable = PrivateAttr()

    def __init__(
        self,
        *,
        structured_outputs: list[BusinessUnderstandingResult],
        ordinary_outputs: list[AIMessage],
    ) -> None:
        super().__init__(
            responses=[
                output.content
                for output in ordinary_outputs
                if isinstance(output.content, str)
            ]
        )
        self._structured_runnable = ScriptedStructuredRunnable(structured_outputs)

    @property
    def structured_calls(self) -> list[list[object]]:
        return self._structured_runnable.calls

    def with_structured_output(self, schema, **kwargs):
        if schema is not BusinessUnderstandingResult or kwargs:
            raise AssertionError("unexpected structured output contract")
        self.structured_schemas.append(schema)
        return self._structured_runnable

    async def ainvoke(
        self,
        input: Any,
        config: Any = None,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> AIMessage:
        self.ordinary_calls.append(list(input))
        return await super().ainvoke(
            input,
            config,
            stop=stop,
            **kwargs,
        )


class RecordingModel(ScriptedChatModel):
    def __init__(self):
        super().__init__(
            structured_outputs=[non_business_result(), non_business_result()],
            ordinary_outputs=[
                AIMessage(content="answer-1"),
                AIMessage(content="answer-2"),
            ],
        )

    @property
    def calls(self):
        return self.ordinary_calls


class FailingModel:
    def __init__(self):
        self.calls = 0
        self.partial_output = "partial"
        self.structured_runnable = ScriptedStructuredRunnable(
            [non_business_result()]
        )

    def with_structured_output(self, schema, **kwargs):
        if schema is not BusinessUnderstandingResult or kwargs:
            raise AssertionError("unexpected structured output contract")
        return self.structured_runnable

    async def ainvoke(self, messages):
        self.calls += 1
        raise RuntimeError("controlled failure after partial output")


class BlockingPartialModel:
    def __init__(self):
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.partial_chunks = []
        self.structured_runnable = ScriptedStructuredRunnable(
            [non_business_result()]
        )

    def with_structured_output(self, schema, **kwargs):
        if schema is not BusinessUnderstandingResult or kwargs:
            raise AssertionError("unexpected structured output contract")
        return self.structured_runnable

    async def ainvoke(self, messages):
        self.calls += 1
        self.partial_chunks.append(AIMessageChunk(content="not-durable"))
        self.started.set()
        await self.release.wait()
        return AIMessage(content="must-not-complete")


@asynccontextmanager
async def isolated_schema():
    schema = f"test_chat_runtime_{uuid4().hex}"
    admin = create_async_engine(DATABASE_URL)
    try:
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    finally:
        await admin.dispose()
    try:
        saver_url = f"{DATABASE_URL}?options=-csearch_path%3D{schema}"
        yield schema, saver_url
    finally:
        cleanup = create_async_engine(DATABASE_URL)
        try:
            async with cleanup.begin() as connection:
                await connection.execute(
                    text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                )
        finally:
            await cleanup.dispose()


def create_business_engine(schema: str):
    return create_async_engine(
        DATABASE_URL,
        connect_args={"server_settings": {"search_path": schema}},
    )
