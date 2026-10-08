import pytest
from faststream.rabbit import RabbitBroker
from sqlalchemy import select

from app.db import make_session_factory
from app.models import Outbox
from app.outbox import publish_pending
from app.payments import create_payment
from app.publisher import RabbitPublisher
from app.schemas import PaymentCreate
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


async def test_create_leaves_outbox_pending_until_relay(api, rabbitmq_url) -> None:
    client, application = api
    created = await client.post(
        "/api/v1/payments",
        json=payment_body(),
        headers={**HEADERS, "Idempotency-Key": "relay-2"},
    )
    payment_id = created.json()["payment_id"]
    async with application.state.session_factory() as session:
        row = await session.scalar(select(Outbox).where(Outbox.aggregate_id == payment_id))
    assert created.status_code == 202
    assert row.status == "pending"
    assert await queue_depth(rabbitmq_url, NEW_QUEUE) == 0


class RecordingPublisher:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    async def publish_outbox(self, payload: dict) -> None:
        self.payloads.append(payload)


async def test_second_relay_skips_row_locked_by_the_first(engine) -> None:
    factory = make_session_factory(engine)
    async with factory() as session:
        payment = await create_payment(session, PaymentCreate.model_validate(payment_body()), "relay-lock")
    holder = factory()
    await holder.begin()
    locked = await holder.scalar(
        select(Outbox).where(Outbox.aggregate_id == payment.id).with_for_update()
    )
    assert locked is not None
    try:
        async with factory() as other:
            published = await publish_pending(other, RecordingPublisher(), batch_size=10)
        assert published == 0
    finally:
        await holder.rollback()
        await holder.close()
    async with factory() as other:
        published = await publish_pending(other, RecordingPublisher(), batch_size=10)
    assert published == 1
