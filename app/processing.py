from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.errors import PaymentNotFoundError, PermanentFailure
from app.gateway import PaymentGateway
from app.models import Payment
from app.webhook import WebhookClient


def webhook_body(payment: Payment) -> dict[str, Any]:
    processed_at = payment.processed_at.isoformat() if payment.processed_at else None
    return {
        "payment_id": str(payment.id),
        "status": payment.status,
        "amount": f"{payment.amount:.2f}",
        "currency": payment.currency,
        "description": payment.description,
        "metadata": payment.payment_metadata,
        "processed_at": processed_at,
    }


class PaymentProcessor:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        gateway: PaymentGateway,
        webhook: WebhookClient,
    ) -> None:
        self._session_factory = session_factory
        self._gateway = gateway
        self._webhook = webhook

    async def process(self, payment_id: UUID) -> None:
        url, payload, needs_gateway = await self._prepare(payment_id)
        if not needs_gateway and url is None:
            return
        if needs_gateway:
            succeeded = await self._gateway.process(payment_id)
            url, payload = await self._apply(payment_id, succeeded)
        if url is None or payload is None:
            raise PermanentFailure(str(payment_id))
        await self._webhook.deliver(url, payload)
        await self._mark_sent(payment_id)

    async def _prepare(self, payment_id: UUID) -> tuple[str | None, dict[str, Any] | None, bool]:
        async with self._session_factory() as session:
            payment = await self._lock(session, payment_id)
            if payment.webhook_sent_at is not None:
                return None, None, False
            if payment.status != "pending":
                return payment.webhook_url, webhook_body(payment), False
            return None, None, True

    async def _apply(self, payment_id: UUID, succeeded: bool) -> tuple[str, dict[str, Any]]:
        async with self._session_factory() as session:
            payment = await self._lock(session, payment_id)
            if payment.status == "pending":
                payment.status = "succeeded" if succeeded else "failed"
                payment.processed_at = datetime.now(timezone.utc)
                await session.commit()
            return payment.webhook_url, webhook_body(payment)

    async def _mark_sent(self, payment_id: UUID) -> None:
        async with self._session_factory() as session:
            payment = await self._lock(session, payment_id)
            payment.webhook_sent_at = datetime.now(timezone.utc)
            await session.commit()

    async def _lock(self, session: AsyncSession, payment_id: UUID) -> Payment:
        statement = select(Payment).where(Payment.id == payment_id)
        if session.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update()
        payment = await session.scalar(statement)
        if payment is None:
            raise PaymentNotFoundError(str(payment_id))
        return payment
