"""Kafka client factories."""

from collections.abc import Iterable

from confluent_kafka import KafkaError, KafkaException
from confluent_kafka.aio import AIOConsumer, AIOProducer
from confluent_kafka.admin import AdminClient, NewTopic


def create_kafka_producer(bootstrap_servers: str) -> AIOProducer:
    """Create an AsyncIO Kafka producer."""

    return AIOProducer({"bootstrap.servers": bootstrap_servers})


def create_kafka_consumer(*, bootstrap_servers: str, group_id: str) -> AIOConsumer:
    """Create an AsyncIO Kafka consumer with manual commits."""

    return AIOConsumer(
        {
            "bootstrap.servers": bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": "false",
        }
    )


def ensure_kafka_topics(
    *,
    bootstrap_servers: str,
    topic_names: Iterable[str],
    num_partitions: int = 1,
    replication_factor: int = 1,
) -> None:
    """Create Kafka topics if they do not already exist."""

    topics = [
        NewTopic(
            topic,
            num_partitions=num_partitions,
            replication_factor=replication_factor,
        )
        for topic in topic_names
    ]
    if not topics:
        return

    admin_client = AdminClient({"bootstrap.servers": bootstrap_servers})
    futures = admin_client.create_topics(topics)
    for future in futures.values():
        try:
            future.result()
        except KafkaException as exc:
            error = exc.args[0] if exc.args else None
            if getattr(error, "code", lambda: None)() == KafkaError.TOPIC_ALREADY_EXISTS:
                continue
            raise
