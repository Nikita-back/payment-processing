import asyncio
import json
import logging

from faststream import FastStream
from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange, RabbitMessage, RabbitQueue

from app.config import get_settings
from app.db import make_engine, make_session_factory, wait_for_schema
from app.delivery import handle_delivery
from app.gateway import PaymentGateway
from app.processing import PaymentProcessor
from app.publisher import RabbitPublisher
from app.topology import PAYMENTS_EXCHANGE, declare_topology, main_queue_spec
from app.webhook import WebhookClient


def consumer_queue() -> RabbitQueue:
    spec = main_queue_spec()
    return RabbitQueue(
        spec.name,
        durable=True,
        routing_key=spec.routing_key,
        arguments=spec.arguments,
    )


def register_consumer(broker: RabbitBroker, processor: PaymentProcessor, publisher: RabbitPublisher) -> None:
    queue = consumer_queue()
    exchange = RabbitExchange(PAYMENTS_EXCHANGE, type=ExchangeType.DIRECT, durable=True)

    @broker.subscriber(queue, exchange)
    async def on_payment_new(message: RabbitMessage) -> None:
        payload = _payload(message)
        headers = dict(message.headers or {})
        await handle_delivery(payload, headers, processor, publisher)


def _payload(message: RabbitMessage) -> dict:
    body = message.body
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        return json.loads(body)
    return json.loads(bytes(body))


async def serve() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    engine = make_engine(settings.database_url)
    await wait_for_schema(engine)
    session_factory = make_session_factory(engine)
    await declare_topology(
        settings.rabbitmq_url,
        settings.retry_base_delay_ms,
        settings.max_delivery_attempts,
    )
    broker = RabbitBroker(settings.rabbitmq_url)
    publisher = RabbitPublisher(broker, settings.max_delivery_attempts)
    gateway = PaymentGateway(
        min_delay_seconds=settings.gateway_min_delay_seconds,
        max_delay_seconds=settings.gateway_max_delay_seconds,
        success_rate=settings.gateway_success_rate,
    )
    webhook = WebhookClient(
        attempts=settings.webhook_attempts,
        base_delay_seconds=settings.webhook_retry_base_seconds,
        timeout_seconds=settings.webhook_timeout_seconds,
    )
    processor = PaymentProcessor(session_factory, gateway, webhook)
    register_consumer(broker, processor, publisher)
    application = FastStream(broker)
    try:
        await application.run()
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
