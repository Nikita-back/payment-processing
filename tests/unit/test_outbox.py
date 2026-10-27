import pytest
from sqlalchemy import select

from app.application.create_payment import CreatePayment
from app.application.publish_outbox import PublishOutbox
from app.infrastructure.db.models import OutboxModel
from tests.helpers import OpenWebhookGuard, payment_request


class RecordingPublisher:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.payloads: list[dict] = []

    async def publish_outbox(self, payload: dict) -> None:
        if self.fail:
            raise ConnectionError("broker down")
        self.payloads.append(payload)


async def _payment(uow_factory, key: str, **overrides):
    async with uow_factory() as uow:
        return await CreatePayment(OpenWebhookGuard()).execute(uow, payment_request(**overrides), key)


async def test_publish_pending_marks_row_published(session_factory, uow_factory) -> None:
    payment = await _payment(uow_factory, "key-1")
    publisher = RecordingPublisher()
    async with uow_factory() as uow:
        published = await PublishOutbox().run(uow, publisher, batch_size=10)
    async with session_factory() as session:
        row = await session.scalar(select(OutboxModel).where(OutboxModel.aggregate_id == payment.id))
    assert published == 1
    assert publisher.payloads == [{"payment_id": str(payment.id)}]
    assert row.status == "published"
    assert row.published_at is not None


async def test_publish_failure_leaves_row_pending(session_factory, uow_factory) -> None:
    payment = await _payment(uow_factory, "key-1")
    publisher = RecordingPublisher(fail=True)
    async with uow_factory() as uow:
        with pytest.raises(ConnectionError):
            await PublishOutbox().run(uow, publisher, batch_size=10)
    async with session_factory() as session:
        row = await session.scalar(select(OutboxModel).where(OutboxModel.aggregate_id == payment.id))
    assert row.status == "pending"
    assert row.published_at is None


class SecondPublishFails:
    def __init__(self) -> None:
        self.calls = 0

    async def publish_outbox(self, payload: dict) -> None:
        self.calls += 1
        if self.calls == 2:
            raise ConnectionError("broker down")


async def test_published_row_stays_published_when_next_publish_fails(session_factory, uow_factory) -> None:
    first = await _payment(uow_factory, "key-1")
    second = await _payment(uow_factory, "key-2", amount="3.00")
    publisher = SecondPublishFails()
    async with uow_factory() as uow:
        with pytest.raises(ConnectionError):
            await PublishOutbox().run(uow, publisher, batch_size=10)
    async with session_factory() as session:
        first_row = await session.scalar(select(OutboxModel).where(OutboxModel.aggregate_id == first.id))
        second_row = await session.scalar(select(OutboxModel).where(OutboxModel.aggregate_id == second.id))
    assert first_row.status == "published"
    assert second_row.status == "pending"
