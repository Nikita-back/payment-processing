import pytest
from sqlalchemy import select

from app.models import Outbox
from app.outbox import publish_pending
from app.payments import create_payment
from app.schemas import PaymentCreate
from tests.helpers import payment_body


class RecordingPublisher:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.payloads: list[dict] = []

    async def publish_outbox(self, payload: dict) -> None:
        if self.fail:
            raise ConnectionError("broker down")
        self.payloads.append(payload)


async def test_publish_pending_marks_row_published(session_factory) -> None:
    async with session_factory() as session:
        payment = await create_payment(session, PaymentCreate.model_validate(payment_body()), "key-1")
    publisher = RecordingPublisher()
    async with session_factory() as session:
        published = await publish_pending(session, publisher, batch_size=10)
        row = await session.scalar(select(Outbox).where(Outbox.aggregate_id == payment.id))
    assert published == 1
    assert publisher.payloads == [{"payment_id": str(payment.id)}]
    assert row.status == "published"
    assert row.published_at is not None


async def test_publish_failure_leaves_row_pending(session_factory) -> None:
    async with session_factory() as session:
        payment = await create_payment(session, PaymentCreate.model_validate(payment_body()), "key-1")
    publisher = RecordingPublisher(fail=True)
    async with session_factory() as session:
        with pytest.raises(ConnectionError):
            await publish_pending(session, publisher, batch_size=10)
    async with session_factory() as session:
        row = await session.scalar(select(Outbox).where(Outbox.aggregate_id == payment.id))
    assert row.status == "pending"
    assert row.published_at is None
