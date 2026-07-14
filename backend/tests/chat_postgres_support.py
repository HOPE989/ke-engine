import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

from langchain_core.messages import AIMessage, AIMessageChunk
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = "postgresql+asyncpg://ke_engine:ke_engine@127.0.0.1:5432/ke_engine"


def unique_thread_id() -> str:
    return uuid4().hex


class RecordingModel:
    def __init__(self):
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(list(messages))
        return AIMessage(content=f"answer-{len(self.calls)}")


class FailingModel:
    def __init__(self):
        self.calls = 0
        self.partial_output = "partial"

    async def ainvoke(self, messages):
        self.calls += 1
        raise RuntimeError("controlled failure after partial output")


class BlockingPartialModel:
    def __init__(self):
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.partial_chunks = []

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
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    await admin.dispose()
    try:
        saver_url = f"{DATABASE_URL}?options=-csearch_path%3D{schema}"
        yield schema, saver_url
    finally:
        cleanup = create_async_engine(DATABASE_URL)
        async with cleanup.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await cleanup.dispose()


def create_business_engine(schema: str):
    return create_async_engine(
        DATABASE_URL,
        connect_args={"server_settings": {"search_path": schema}},
    )
