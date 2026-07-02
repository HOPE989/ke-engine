import pytest


@pytest.mark.asyncio
async def test_start_worker_consumers_runs_document_convert(monkeypatch):
    from app.workers import kafka_worker

    calls = []

    class FakeTaskGroup:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def create_task(self, coroutine):
            calls.append(coroutine)
            coroutine.close()

    async def fake_document_consumer():
        return None

    monkeypatch.setattr(kafka_worker.asyncio, "TaskGroup", FakeTaskGroup)
    monkeypatch.setattr(kafka_worker, "run_document_conversion_consumer", fake_document_consumer)

    await kafka_worker.start_worker_consumers()

    assert len(calls) == 1
