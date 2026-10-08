import pytest
from sqlalchemy import func, select

from app.errors import IdempotencyConflictError, PaymentNotFoundError
from app.models import Outbox, Payment
from app.payments import create_payment, get_payment
from app.schemas import PaymentCreate
from tests.helpers import payment_body


async def test_create_writes_payment_and_outbox(session_factory) -> None:
    body = PaymentCreate.model_validate(payment_body())
    async with session_factory() as session:
        payment = await create_payment(session, body, "key-1")
    async with session_factory() as session:
        stored = await get_payment(session, payment.id)
        outbox = await session.scalar(select(Outbox).where(Outbox.aggregate_id == payment.id))
    assert stored.status == "pending"
    assert stored.currency == "RUB"
    assert str(stored.amount) == "12.30"
    assert stored.payment_metadata == {"order_id": "42"}
    assert outbox is not None
    assert outbox.status == "pending"
    assert outbox.event_type == "payments.new"
    assert outbox.payload == {"payment_id": str(payment.id)}


async def test_same_key_and_body_returns_existing_payment(session_factory) -> None:
    body = PaymentCreate.model_validate(payment_body())
    async with session_factory() as session:
        first = await create_payment(session, body, "key-1")
    async with session_factory() as session:
        second = await create_payment(session, body, "key-1")
        count = await session.scalar(select(func.count()).select_from(Payment))
    assert second.id == first.id
    assert count == 1


async def test_same_key_and_different_body_conflicts(session_factory) -> None:
    async with session_factory() as session:
        await create_payment(session, PaymentCreate.model_validate(payment_body()), "key-1")
    async with session_factory() as session:
        with pytest.raises(IdempotencyConflictError):
            await create_payment(
                session,
                PaymentCreate.model_validate(payment_body(amount="99.00")),
                "key-1",
            )


async def test_failed_commit_keeps_database_empty(session_factory) -> None:
    async with session_factory() as session:
        original = session.commit

        async def broken_commit():
            raise RuntimeError("disk")

        session.commit = broken_commit
        with pytest.raises(RuntimeError):
            await create_payment(session, PaymentCreate.model_validate(payment_body()), "key-1")
        session.commit = original
    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Payment))
    assert count == 0


async def test_get_missing_payment(session_factory) -> None:
    from uuid import uuid4

    async with session_factory() as session:
        with pytest.raises(PaymentNotFoundError):
            await get_payment(session, uuid4())
