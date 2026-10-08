import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import IdempotencyConflictError, PaymentNotFoundError
from app.fingerprint import normalize_amount, request_hash
from app.models import Outbox, Payment
from app.schemas import PaymentCreate


async def create_payment(session: AsyncSession, body: PaymentCreate, idempotency_key: str) -> Payment:
    digest = request_hash(body)
    existing = await _by_key(session, idempotency_key)
    if existing is not None:
        _ensure_same(existing, digest)
        return existing

    now = datetime.now(timezone.utc)
    payment = Payment(
        id=uuid.uuid4(),
        amount=normalize_amount(body.amount),
        currency=body.currency,
        description=body.description,
        payment_metadata=body.metadata,
        status="pending",
        idempotency_key=idempotency_key,
        request_hash=digest,
        webhook_url=str(body.webhook_url),
        created_at=now,
    )
    session.add(payment)
    session.add(
        Outbox(
            id=uuid.uuid4(),
            aggregate_id=payment.id,
            event_type="payments.new",
            payload={"payment_id": str(payment.id)},
            status="pending",
            created_at=now,
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await _by_key(session, idempotency_key)
        if existing is None:
            raise
        _ensure_same(existing, digest)
        return existing
    except Exception:
        await session.rollback()
        raise
    return payment


async def get_payment(session: AsyncSession, payment_id: UUID) -> Payment:
    payment = await session.get(Payment, payment_id)
    if payment is None:
        raise PaymentNotFoundError(str(payment_id))
    return payment


async def _by_key(session: AsyncSession, idempotency_key: str) -> Payment | None:
    return await session.scalar(select(Payment).where(Payment.idempotency_key == idempotency_key))


def _ensure_same(payment: Payment, digest: str) -> None:
    if payment.request_hash != digest:
        raise IdempotencyConflictError(payment.idempotency_key)
