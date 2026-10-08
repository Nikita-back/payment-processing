from app.publisher import RabbitPublisher
from app.topology import DLQ_ROUTING_KEY, NEW_ROUTING_KEY
from app.retry import retry_routing_key


class FakeBroker:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, dict]] = []

    async def publish(self, message: dict, **kwargs) -> None:
        self.calls.append((message, kwargs))


async def test_outbox_publish_goes_to_payments_new() -> None:
    broker = FakeBroker()
    publisher = RabbitPublisher(broker, max_attempts=3)
    await publisher.publish_outbox({"payment_id": "1"})
    message, kwargs = broker.calls[0]
    assert message == {"payment_id": "1"}
    assert kwargs["routing_key"] == NEW_ROUTING_KEY
    assert kwargs["headers"]["x-attempt"] == 0
    assert kwargs["persist"] is True


async def test_retry_uses_exponential_queue_then_dlq() -> None:
    broker = FakeBroker()
    publisher = RabbitPublisher(broker, max_attempts=3)
    await publisher.publish_retry({"payment_id": "1"}, 0)
    await publisher.publish_retry({"payment_id": "1"}, 1)
    await publisher.publish_retry({"payment_id": "1"}, 2)
    assert broker.calls[0][1]["routing_key"] == retry_routing_key(0)
    assert broker.calls[0][1]["headers"]["x-attempt"] == 1
    assert broker.calls[1][1]["routing_key"] == retry_routing_key(1)
    assert broker.calls[1][1]["headers"]["x-attempt"] == 2
    assert broker.calls[2][1]["routing_key"] == DLQ_ROUTING_KEY
    assert broker.calls[2][1]["headers"]["x-attempt"] == 3
