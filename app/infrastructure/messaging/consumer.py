import json

from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange, RabbitMessage, RabbitQueue

from app.application.ports import AttemptPublisher
from app.infrastructure.messaging.delivery import handle_delivery
from app.infrastructure.messaging.topology import PAYMENTS_EXCHANGE, main_queue_spec


def consumer_queue() -> RabbitQueue:
    spec = main_queue_spec()
    return RabbitQueue(
        spec.name,
        durable=True,
        routing_key=spec.routing_key,
        arguments=spec.arguments,
    )


def register_consumer(broker: RabbitBroker, processor, publisher: AttemptPublisher) -> None:
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
