def test_create_kafka_producer_uses_bootstrap_servers(monkeypatch):
    from app.infrastructure import kafka

    created_configs = []

    class FakeProducer:
        def __init__(self, config):
            created_configs.append(config)

    monkeypatch.setattr(kafka, "AIOProducer", FakeProducer)

    producer = kafka.create_kafka_producer("kafka.example:9092")

    assert isinstance(producer, FakeProducer)
    assert created_configs == [{"bootstrap.servers": "kafka.example:9092"}]


def test_create_kafka_consumer_disables_auto_commit(monkeypatch):
    from app.infrastructure import kafka

    created_configs = []

    class FakeConsumer:
        def __init__(self, config):
            created_configs.append(config)

    monkeypatch.setattr(kafka, "AIOConsumer", FakeConsumer)

    consumer = kafka.create_kafka_consumer(
        bootstrap_servers="kafka.example:9092",
        group_id="group-a",
    )

    assert isinstance(consumer, FakeConsumer)
    assert created_configs == [
        {
            "bootstrap.servers": "kafka.example:9092",
            "group.id": "group-a",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": "false",
        }
    ]
