"""Kafka client factories."""

from confluent_kafka.aio import AIOConsumer, AIOProducer


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
