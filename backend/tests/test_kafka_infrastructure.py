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


def test_ensure_kafka_topics_creates_missing_topics(monkeypatch):
    from app.infrastructure import kafka

    created_admin_configs = []
    created_topics = []

    class FakeFuture:
        def result(self):
            return None

    class FakeAdminClient:
        def __init__(self, config):
            created_admin_configs.append(config)

        def create_topics(self, topics):
            created_topics.extend(topics)
            return {topic.topic: FakeFuture() for topic in topics}

    class FakeNewTopic:
        def __init__(self, topic, *, num_partitions, replication_factor):
            self.topic = topic
            self.num_partitions = num_partitions
            self.replication_factor = replication_factor

    monkeypatch.setattr(kafka, "AdminClient", FakeAdminClient)
    monkeypatch.setattr(kafka, "NewTopic", FakeNewTopic)

    kafka.ensure_kafka_topics(
        bootstrap_servers="kafka.example:9092",
        topic_names=["document.convert.requested"],
    )

    assert created_admin_configs == [{"bootstrap.servers": "kafka.example:9092"}]
    assert [(topic.topic, topic.num_partitions, topic.replication_factor) for topic in created_topics] == [
        ("document.convert.requested", 1, 1)
    ]


def test_ensure_kafka_topics_keeps_admin_client_alive_until_futures_complete(monkeypatch):
    from app.infrastructure import kafka

    admin_state = {"alive": False}

    class FakeFuture:
        def result(self):
            assert admin_state["alive"] is True

    class FakeAdminClient:
        def __init__(self, config):
            admin_state["alive"] = True

        def __del__(self):
            admin_state["alive"] = False

        def create_topics(self, topics):
            return {topic.topic: FakeFuture() for topic in topics}

    class FakeNewTopic:
        def __init__(self, topic, *, num_partitions, replication_factor):
            self.topic = topic

    monkeypatch.setattr(kafka, "AdminClient", FakeAdminClient)
    monkeypatch.setattr(kafka, "NewTopic", FakeNewTopic)

    kafka.ensure_kafka_topics(
        bootstrap_servers="kafka.example:9092",
        topic_names=["document.convert.requested"],
    )
