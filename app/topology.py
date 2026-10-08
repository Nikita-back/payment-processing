from dataclasses import dataclass

import aio_pika
from aio_pika import ExchangeType

from app.retry import retry_delay_ms, retry_queue_name, retry_routing_key

PAYMENTS_EXCHANGE = "payments"
DLX_EXCHANGE = "payments.dlx"
NEW_QUEUE = "payments.new"
NEW_ROUTING_KEY = "payments.new"
DLQ_QUEUE = "payments.new.dlq"
DLQ_ROUTING_KEY = "payments.new.dlq"


@dataclass(frozen=True)
class QueueSpec:
    name: str
    routing_key: str
    exchange: str
    arguments: dict | None


def queue_specs(base_delay_ms: int, max_attempts: int) -> list[QueueSpec]:
    specs = [
        QueueSpec(
            name=DLQ_QUEUE,
            routing_key=DLQ_ROUTING_KEY,
            exchange=DLX_EXCHANGE,
            arguments={"x-queue-type": "classic"},
        ),
        QueueSpec(
            name=NEW_QUEUE,
            routing_key=NEW_ROUTING_KEY,
            exchange=PAYMENTS_EXCHANGE,
            arguments={
                "x-dead-letter-exchange": DLX_EXCHANGE,
                "x-dead-letter-routing-key": DLQ_ROUTING_KEY,
                "x-queue-type": "classic",
            },
        ),
    ]
    for attempt in range(max_attempts - 1):
        specs.append(
            QueueSpec(
                name=retry_queue_name(attempt),
                routing_key=retry_routing_key(attempt),
                exchange=PAYMENTS_EXCHANGE,
                arguments={
                    "x-message-ttl": retry_delay_ms(attempt, base_delay_ms),
                    "x-dead-letter-exchange": PAYMENTS_EXCHANGE,
                    "x-dead-letter-routing-key": NEW_ROUTING_KEY,
                    "x-queue-type": "classic",
                },
            )
        )
    return specs


def main_queue_spec() -> QueueSpec:
    for spec in queue_specs(1, 2):
        if spec.name == NEW_QUEUE:
            return spec
    raise RuntimeError("payments.new spec is missing")


async def declare_topology(amqp_url: str, base_delay_ms: int, max_attempts: int) -> None:
    connection = await aio_pika.connect_robust(amqp_url)
    try:
        channel = await connection.channel()
        exchanges = {
            PAYMENTS_EXCHANGE: await channel.declare_exchange(
                PAYMENTS_EXCHANGE,
                ExchangeType.DIRECT,
                durable=True,
            ),
            DLX_EXCHANGE: await channel.declare_exchange(
                DLX_EXCHANGE,
                ExchangeType.DIRECT,
                durable=True,
            ),
        }
        for spec in queue_specs(base_delay_ms, max_attempts):
            queue = await channel.declare_queue(spec.name, durable=True, arguments=spec.arguments)
            await queue.bind(exchanges[spec.exchange], routing_key=spec.routing_key)
    finally:
        await connection.close()
