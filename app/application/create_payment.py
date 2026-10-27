from datetime import datetime, timezone

from app.application.errors import UniqueViolation
from app.application.ports import UnitOfWork, WebhookGuard
from app.domain.errors import BlankIdempotencyKey
from app.domain.outbox import OutboxMessage
from app.domain.payment import Payment
from app.domain.request import PaymentRequest, request_hash


class CreatePayment:
    def __init__(self, webhook_guard: WebhookGuard) -> None:
        self._webhook_guard = webhook_guard

    async def execute(self, uow: UnitOfWork, request: PaymentRequest, idempotency_key: str) -> Payment:
        key = idempotency_key.strip()
        if not key:
            raise BlankIdempotencyKey()
        self._webhook_guard.ensure(request.webhook_url)
        digest = request_hash(request)
        existing = await uow.payments.find_by_idempotency_key(key)
        if existing is not None:
            existing.ensure_same_request(digest)
            return existing
        now = datetime.now(timezone.utc)
        payment = Payment.open(request, key, digest, now)
        uow.payments.add(payment)
        uow.outbox.add(OutboxMessage.for_payment(payment.id, now))
        try:
            await uow.commit()
        except UniqueViolation:
            await uow.rollback()
            existing = await uow.payments.find_by_idempotency_key(key)
            if existing is None:
                raise
            existing.ensure_same_request(digest)
            return existing
        except Exception:
            await uow.rollback()
            raise
        return payment
