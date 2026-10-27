from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from app.application.ports import Gateway, UnitOfWork, WebhookSender
from app.domain.errors import PaymentNotFoundError, PermanentFailure
from app.domain.payment import Payment, ProcessingStep


class ProcessPayment:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        gateway: Gateway,
        webhook: WebhookSender,
        claim_lease_seconds: float = 30.0,
    ) -> None:
        self._uow_factory = uow_factory
        self._gateway = gateway
        self._webhook = webhook
        self._claim_lease = timedelta(seconds=claim_lease_seconds)

    async def process(self, payment_id: UUID) -> None:
        step = await self._prepare(payment_id)
        url = step.webhook_url
        payload = step.payload
        if not step.needs_gateway and url is None:
            return
        if step.needs_gateway:
            try:
                succeeded = await self._gateway.process(payment_id)
            except Exception:
                await self._release_claim(payment_id)
                raise
            url, payload = await self._apply(payment_id, succeeded)
        if url is None or payload is None:
            raise PermanentFailure(str(payment_id))
        await self._webhook.deliver(url, payload)
        await self._mark_sent(payment_id)

    async def _prepare(self, payment_id: UUID) -> ProcessingStep:
        async with self._uow_factory() as uow:
            payment = await self._lock(uow, payment_id)
            step = payment.begin_processing(datetime.now(timezone.utc), self._claim_lease)
            if step.needs_gateway:
                await uow.commit()
            return step

    async def _release_claim(self, payment_id: UUID) -> None:
        async with self._uow_factory() as uow:
            payment = await self._lock(uow, payment_id)
            payment.release_claim()
            await uow.commit()

    async def _apply(self, payment_id: UUID, succeeded: bool) -> tuple[str, dict[str, Any]]:
        async with self._uow_factory() as uow:
            payment = await self._lock(uow, payment_id)
            payment.finish(succeeded, datetime.now(timezone.utc))
            await uow.commit()
            return payment.webhook_url, payment.notification()

    async def _mark_sent(self, payment_id: UUID) -> None:
        async with self._uow_factory() as uow:
            payment = await self._lock(uow, payment_id)
            payment.mark_notified(datetime.now(timezone.utc))
            await uow.commit()

    async def _lock(self, uow: UnitOfWork, payment_id: UUID) -> Payment:
        payment = await uow.payments.get_for_update(payment_id)
        if payment is None:
            raise PaymentNotFoundError(str(payment_id))
        return payment
