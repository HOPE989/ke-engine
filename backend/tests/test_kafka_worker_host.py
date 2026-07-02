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


@pytest.mark.asyncio
async def test_worker_main_configures_logging_before_starting_consumers(monkeypatch):
    from app.workers import kafka_worker

    calls = []

    def fake_configure_logging():
        calls.append("configure_logging")

    async def fake_start_worker_consumers():
        calls.append("start_worker_consumers")

    monkeypatch.setattr(kafka_worker, "configure_logging", fake_configure_logging)
    monkeypatch.setattr(kafka_worker, "start_worker_consumers", fake_start_worker_consumers)

    await kafka_worker.main()

    assert calls == ["configure_logging", "start_worker_consumers"]
