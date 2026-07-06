import pytest


@pytest.mark.asyncio
async def test_start_worker_consumers_owns_runtime_stack_and_runs_document_workers_with_shared_runtime(monkeypatch):
    from app.workers import kafka_worker

    calls = []
    settings = object()
    shared_runtime = object()

    class FakeRuntimeStack:
        async def __aenter__(self):
            calls.append(("enter_stack", None))
            return self

        async def __aexit__(self, exc_type, exc, tb):
            calls.append(("exit_stack", None))
            return None

    class FakeTaskGroup:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def create_task(self, coroutine):
            calls.append(coroutine)
            coroutine.close()

    async def fake_create_kafka_worker_runtime(*, stack, settings):
        calls.append(("create_runtime", stack, settings))
        return shared_runtime

    def fake_document_consumer(runtime):
        calls.append(("conversion_runtime", runtime is shared_runtime))
        async def noop():
            return None

        return noop()

    def fake_vector_storage_consumer(runtime):
        calls.append(("vector_runtime", runtime is shared_runtime))
        async def noop():
            return None

        return noop()

    monkeypatch.setattr(kafka_worker.asyncio, "TaskGroup", FakeTaskGroup)
    monkeypatch.setattr(kafka_worker, "RuntimeResourceStack", FakeRuntimeStack)
    monkeypatch.setattr(kafka_worker, "get_settings", lambda: settings)
    monkeypatch.setattr(
        kafka_worker,
        "create_kafka_worker_runtime",
        fake_create_kafka_worker_runtime,
    )
    monkeypatch.setattr(kafka_worker, "run_document_conversion_consumer", fake_document_consumer)
    monkeypatch.setattr(
        kafka_worker,
        "run_document_vector_storage_consumer",
        fake_vector_storage_consumer,
    )

    await kafka_worker.start_worker_consumers()

    assert calls[0] == ("enter_stack", None)
    assert calls[1] == ("create_runtime", calls[1][1], settings)
    assert calls[-1] == ("exit_stack", None)
    assert ("conversion_runtime", True) in calls
    assert ("vector_runtime", True) in calls
    assert len([call for call in calls if not isinstance(call, tuple)]) == 2


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
