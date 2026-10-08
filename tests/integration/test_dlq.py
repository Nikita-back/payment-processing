from uuid import uuid4

import pytest
from faststream.rabbit import RabbitBroker

from app.consumer import register_consumer
from app.publisher import RabbitPublisher
from app.topology import DLQ_QUEUE, NEW_QUEUE
from tests.helpers import wait_for
from tests.integration.conftest import queue_depth

pytestmark = pytest.mark.integration


class AlwaysFail:
    def __init__(self) -> None:
        self.calls = 0

    async def process(self, payment_id) -> None:
        self.calls += 1
        raise RuntimeError("downstream is down")


async def test_retry_queue_returns_message_to_main(rabbitmq_url) -> None:
    broker = RabbitBroker(rabbitmq_url)
    await broker.start()
    try:
        publisher = RabbitPublisher(broker, max_attempts=3)
        await publisher.publish_retry({"payment_id": str(uuid4())}, 0)

        async def arrived() -> bool:
            return await queue_depth(rabbitmq_url, NEW_QUEUE) >= 1

        await wait_for(arrived, timeout=5)
    finally:
        await broker.stop()


async def test_message_is_dead_lettered_after_three_attempts(rabbitmq_url) -> None:
    processor = AlwaysFail()
    broker = RabbitBroker(rabbitmq_url)
    publisher = RabbitPublisher(broker, max_attempts=3)
    register_consumer(broker, processor, publisher)
    await broker.start()
    try:
        await publisher.publish_outbox({"payment_id": str(uuid4())})

        async def landed() -> bool:
            return await queue_depth(rabbitmq_url, DLQ_QUEUE) >= 1

        await wait_for(landed, timeout=10)
        assert processor.calls == 3
    finally:
        await broker.stop()
