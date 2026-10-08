from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange

from app.retry import retry_routing_key, should_dead_letter
from app.topology import DLQ_ROUTING_KEY, DLX_EXCHANGE, NEW_ROUTING_KEY, PAYMENTS_EXCHANGE


class RabbitPublisher:
    def __init__(self, broker: RabbitBroker, max_attempts: int) -> None:
        self._broker = broker
        self._max_attempts = max_attempts
        self._payments = RabbitExchange(PAYMENTS_EXCHANGE, type=ExchangeType.DIRECT, durable=True)
        self._dlx = RabbitExchange(DLX_EXCHANGE, type=ExchangeType.DIRECT, durable=True)

    async def publish_outbox(self, payload: dict) -> None:
        await self._broker.publish(
            payload,
            exchange=self._payments,
            routing_key=NEW_ROUTING_KEY,
            headers={"x-attempt": 0},
            persist=True,
        )

    async def publish_retry(self, payload: dict, attempt: int) -> None:
        if should_dead_letter(attempt, self._max_attempts):
            await self.publish_dlq(payload, attempt + 1)
            return
        await self._broker.publish(
            payload,
            exchange=self._payments,
            routing_key=retry_routing_key(attempt),
            headers={"x-attempt": attempt + 1},
            persist=True,
        )

    async def publish_dlq(self, payload: dict, attempt: int) -> None:
        await self._broker.publish(
            payload,
            exchange=self._dlx,
            routing_key=DLQ_ROUTING_KEY,
            headers={"x-attempt": attempt},
            persist=True,
        )
