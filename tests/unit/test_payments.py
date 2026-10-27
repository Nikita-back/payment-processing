import pytest
from sqlalchemy import func, select

from app.application.create_payment import CreatePayment
from app.application.get_payment import GetPayment
from app.domain.errors import BlankIdempotencyKey, IdempotencyConflictError, PaymentNotFoundError, WebhookURLRejected
from app.infrastructure.db.models import OutboxModel, PaymentModel
from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from app.infrastructure.netpolicy import NetworkWebhookGuard
from tests.helpers import OpenWebhookGuard, payment_request


def _service() -> CreatePayment:
    return CreatePayment(OpenWebhookGuard())


async def test_create_writes_payment_and_outbox(session_factory, uow_factory) -> None:
    async with uow_factory() as uow:
        payment = await _service().execute(uow, payment_request(), "key-1")
    async with uow_factory() as uow:
        stored = await GetPayment().execute(uow, payment.id)
    async with session_factory() as session:
        outbox = await session.scalar(select(OutboxModel).where(OutboxModel.aggregate_id == payment.id))
    assert stored.status == "pending"
    assert stored.currency == "RUB"
    assert str(stored.amount) == "12.30"
    assert stored.metadata == {"order_id": "42"}
    assert outbox is not None
    assert outbox.status == "pending"
    assert outbox.event_type == "payments.new"
    assert outbox.payload == {"payment_id": str(payment.id)}


async def test_same_key_and_body_returns_existing_payment(session_factory, uow_factory) -> None:
    body = payment_request()
    async with uow_factory() as uow:
        first = await _service().execute(uow, body, "key-1")
    async with uow_factory() as uow:
        second = await _service().execute(uow, body, "key-1")
    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(PaymentModel))
    assert second.id == first.id
    assert count == 1


async def test_same_key_and_different_body_conflicts(uow_factory) -> None:
    async with uow_factory() as uow:
        await _service().execute(uow, payment_request(), "key-1")
    async with uow_factory() as uow:
        with pytest.raises(IdempotencyConflictError):
            await _service().execute(uow, payment_request(amount="99.00"), "key-1")


async def test_failed_commit_keeps_database_empty(session_factory) -> None:
    class FailingUnitOfWork(SqlAlchemyUnitOfWork):
        async def commit(self) -> None:
            raise RuntimeError("disk")

    with pytest.raises(RuntimeError):
        async with FailingUnitOfWork(session_factory) as uow:
            await _service().execute(uow, payment_request(), "key-1")
    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(PaymentModel))
    assert count == 0


async def test_get_missing_payment(uow_factory) -> None:
    from uuid import uuid4

    async with uow_factory() as uow:
        with pytest.raises(PaymentNotFoundError):
            await GetPayment().execute(uow, uuid4())


async def test_blank_key_is_a_domain_rule(uow_factory) -> None:
    async with uow_factory() as uow:
        with pytest.raises(BlankIdempotencyKey):
            await _service().execute(uow, payment_request(), "   ")


async def test_private_webhook_is_rejected_before_insert(session_factory, uow_factory) -> None:
    service = CreatePayment(NetworkWebhookGuard(allow_private_networks=False))
    with pytest.raises(WebhookURLRejected):
        async with uow_factory() as uow:
            await service.execute(uow, payment_request(webhook_url="http://127.0.0.1/hook"), "key-1")
    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(PaymentModel))
    assert count == 0
