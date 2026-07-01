import importlib


def test_snowflake_id_generator_returns_monotonic_64_bit_ids(monkeypatch):
    from app.infrastructure.snowflake import SnowflakeIdGenerator

    timestamps = iter([1_800_000_000_000, 1_800_000_000_000, 1_800_000_000_001])
    monkeypatch.setattr(
        "app.infrastructure.snowflake.current_time_millis",
        lambda: next(timestamps),
    )
    generator = SnowflakeIdGenerator(worker_id=7)

    first = generator.next_id()
    second = generator.next_id()
    third = generator.next_id()

    assert first < second < third
    assert first.bit_length() <= 63


def test_conversion_dispatcher_uses_celery_apply_async(monkeypatch):
    from app.modules.document import tasks

    calls = []

    class FakeTask:
        def apply_async(self, *, args):
            calls.append(args)

    monkeypatch.setattr(tasks, "convert_document", FakeTask())

    tasks.CeleryDocumentConversionDispatcher().dispatch(42)

    assert calls == [(42,)]


def test_celery_app_uses_redis_broker_and_json_serializer(monkeypatch):
    from app.core import config

    class FakeSettings:
        celery_broker_url = "redis://redis.example:6379/4"
        celery_result_backend = "redis://redis.example:6379/5"

    monkeypatch.setattr(config, "get_settings", lambda: FakeSettings())

    module = importlib.import_module("app.infrastructure.celery")
    module = importlib.reload(module)

    assert module.celery_app.conf.broker_url == "redis://redis.example:6379/4"
    assert module.celery_app.conf.result_backend == "redis://redis.example:6379/5"
    assert module.celery_app.conf.task_serializer == "json"
    assert module.celery_app.conf.accept_content == ["json"]
