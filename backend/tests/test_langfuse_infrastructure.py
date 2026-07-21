import importlib.util
from types import SimpleNamespace

import pytest


def _settings(**overrides):
    values = {
        "app_version": "0.1.0",
        "langfuse_public_key": "pk-test",
        "langfuse_secret_key": "sk-test",
        "langfuse_base_url": "http://langfuse.example:3000",
        "langfuse_environment": "test",
        "langfuse_release": "release-1",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeLangfuse:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeHandler:
    def __init__(self, *, public_key):
        self.public_key = public_key


class RecordingContext:
    def __init__(self, value=None, *, enter_error=None, exit_error=None):
        self.value = value
        self.enter_error = enter_error
        self.exit_error = exit_error
        self.entered = False
        self.exit_calls = []

    def __enter__(self):
        self.entered = True
        if self.enter_error is not None:
            raise self.enter_error
        return self.value

    def __exit__(self, exc_type, exc, tb):
        self.exit_calls.append((exc_type, exc, tb))
        if self.exit_error is not None:
            raise self.exit_error
        return True


class TraceClient:
    def __init__(self, observation_context):
        self.observation_context = observation_context
        self.start_kwargs = None

    def start_as_current_observation(self, **kwargs):
        self.start_kwargs = kwargs
        return self.observation_context


class RecordingSpan:
    def __init__(self, *, update_error=None):
        self.update_error = update_error
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)
        if self.update_error is not None:
            raise self.update_error


def test_langfuse_dependency_is_available():
    assert importlib.util.find_spec("langfuse") is not None


def test_create_langfuse_resources_returns_none_for_incomplete_configuration():
    from app.infrastructure.langfuse import create_langfuse_resources

    for missing in ["langfuse_public_key", "langfuse_secret_key", "langfuse_base_url"]:
        assert create_langfuse_resources(_settings(**{missing: "  "})) is None


def test_create_langfuse_resources_builds_one_client_and_handler(monkeypatch):
    from app.infrastructure import langfuse as module

    monkeypatch.setattr(module, "Langfuse", FakeLangfuse)
    monkeypatch.setattr(module, "CallbackHandler", FakeHandler)

    resources = module.create_langfuse_resources(_settings())

    assert resources is not None
    assert resources.client.kwargs == {
        "public_key": "pk-test",
        "secret_key": "sk-test",
        "base_url": "http://langfuse.example:3000",
        "environment": "test",
        "release": "release-1",
    }
    assert resources.handler.public_key == "pk-test"


def test_create_langfuse_resources_uses_app_version_as_release_fallback(monkeypatch):
    from app.infrastructure import langfuse as module

    monkeypatch.setattr(module, "Langfuse", FakeLangfuse)
    monkeypatch.setattr(module, "CallbackHandler", FakeHandler)

    resources = module.create_langfuse_resources(_settings(langfuse_release="  "))

    assert resources is not None
    assert resources.client.kwargs["release"] == "0.1.0"


def test_create_langfuse_resources_is_fail_open_on_client_or_handler_error(monkeypatch):
    from app.infrastructure import langfuse as module

    def fail_client(**kwargs):
        raise RuntimeError("client failed")

    monkeypatch.setattr(module, "Langfuse", fail_client)
    assert module.create_langfuse_resources(_settings()) is None

    monkeypatch.setattr(module, "Langfuse", FakeLangfuse)
    monkeypatch.setattr(module, "CallbackHandler", fail_client)
    assert module.create_langfuse_resources(_settings()) is None


def test_completion_trace_without_resources_is_a_noop():
    from app.infrastructure.langfuse import completion_trace

    with completion_trace(
        None,
        input={"content": "raw"},
        session_id="1",
        user_id="user-1",
        metadata={"model": "test"},
        tags=["chat"],
    ) as span:
        assert span is None


def test_completion_trace_records_input_and_propagated_attributes(monkeypatch):
    from app.infrastructure import langfuse as module

    span = RecordingSpan()
    observation_context = RecordingContext(span)
    attribute_context = RecordingContext()
    attribute_kwargs = {}
    client = TraceClient(observation_context)

    def fake_propagate_attributes(**kwargs):
        attribute_kwargs.update(kwargs)
        return attribute_context

    monkeypatch.setattr(module, "propagate_attributes", fake_propagate_attributes)
    resources = module.LangfuseResources(client=client, handler=object())

    with module.completion_trace(
        resources,
        input={"content": "raw"},
        session_id="12",
        user_id="user-1",
        metadata={"model": "test"},
        tags=["chat", "langgraph"],
    ) as current_span:
        assert current_span is span

    assert client.start_kwargs == {
        "as_type": "span",
        "name": "chat-completion",
        "input": {"content": "raw"},
    }
    assert attribute_kwargs == {
        "session_id": "12",
        "user_id": "user-1",
        "metadata": {"model": "test"},
        "tags": ["chat", "langgraph"],
    }
    assert attribute_context.entered is True
    assert observation_context.exit_calls == [(None, None, None)]


def test_completion_trace_falls_back_when_observation_or_attributes_cannot_enter(
    monkeypatch,
):
    from app.infrastructure import langfuse as module

    failing_observation = RecordingContext(enter_error=RuntimeError("start failed"))
    resources = module.LangfuseResources(
        client=TraceClient(failing_observation),
        handler=object(),
    )
    with module.completion_trace(
        resources,
        input={},
        session_id="1",
        user_id="user-1",
        metadata={},
        tags=[],
    ) as span:
        assert span is None

    actual_span = RecordingSpan()
    observation = RecordingContext(actual_span)
    monkeypatch.setattr(
        module,
        "propagate_attributes",
        lambda **kwargs: RecordingContext(enter_error=RuntimeError("attributes failed")),
    )
    resources = module.LangfuseResources(client=TraceClient(observation), handler=object())
    with module.completion_trace(
        resources,
        input={},
        session_id="1",
        user_id="user-1",
        metadata={},
        tags=[],
    ) as span:
        assert span is actual_span
    assert observation.exit_calls == [(None, None, None)]


def test_completion_trace_cleanup_cannot_suppress_or_replace_business_error(monkeypatch):
    from app.infrastructure import langfuse as module

    span = RecordingSpan()
    observation = RecordingContext(span, exit_error=RuntimeError("observation exit"))
    attributes = RecordingContext(exit_error=RuntimeError("attributes exit"))
    monkeypatch.setattr(module, "propagate_attributes", lambda **kwargs: attributes)
    resources = module.LangfuseResources(client=TraceClient(observation), handler=object())

    with pytest.raises(ValueError, match="business failed"):
        with module.completion_trace(
            resources,
            input={},
            session_id="1",
            user_id="user-1",
            metadata={},
            tags=[],
        ):
            raise ValueError("business failed")

    assert observation.exit_calls[0][0] is ValueError
    assert attributes.exit_calls[0][0] is ValueError


def test_safe_update_trace_ignores_missing_span_and_update_error():
    from app.infrastructure.langfuse import safe_update_trace

    safe_update_trace(None, output={"status": "completed"})
    span = RecordingSpan(update_error=RuntimeError("update failed"))
    safe_update_trace(span, output={"status": "completed"})
    assert span.updates == [{"output": {"status": "completed"}}]


@pytest.mark.asyncio
async def test_shutdown_langfuse_calls_client_and_is_fail_open():
    from app.infrastructure.langfuse import LangfuseResources, shutdown_langfuse

    calls = []

    class Client:
        def shutdown(self):
            calls.append("shutdown")
            raise RuntimeError("shutdown failed")

    await shutdown_langfuse(LangfuseResources(client=Client(), handler=object()))
    assert calls == ["shutdown"]
