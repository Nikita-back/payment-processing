import pytest
from faststream.rabbit import RabbitBroker
from sqlalchemy import select

from app.models import Outbox
from app.outbox import publish_pending
from app.publisher import RabbitPublisher
from app.topology import NEW_QUEUE
from tests.helpers import HEADERS, payment_body
from tests.integration.conftest import queue_depth

pytestmark = pytest.mark.integration


async def test_relay_publishes_payments_new_and_marks_outbox(api, rabbitmq_url) -> None:
    client, application = api
    created = await client.post(
        "/api/v1/payments",
        json=payment_body(),
        headers={**HEADERS, "Idempotency-Key": "relay-1"},
    )
    payment_id = created.json()["payment_id"]
    broker = RabbitBroker(rabbitmq_url)
    await broker.start()
    try:
        publisher = RabbitPublisher(broker, max_attempts=3)
        async with application.state.session_factory() as session:
            published = await publish_pending(session, publisher, batch_size=10)
            row = await session.scalar(select(Outbox).where(Outbox.aggregate_id == payment_id))
        assert published == 1
        assert row.status == "published"
        assert row.payload["payment_id"] == payment_id
        assert await queue_depth(rabbitmq_url, NEW_QUEUE) == 1
    finally:
        await broker.stop()
