from typing import Any, Protocol
from uuid import UUID

from app.domain.outbox import OutboxMessage
from app.domain.payment import Payment


class PaymentRepository(Protocol):
    def add(self, payment: Payment) -> None: ...

    async def get(self, payment_id: UUID) -> Payment | None: ...

    async def get_for_update(self, payment_id: UUID) -> Payment | None: ...

    async def find_by_idempotency_key(self, key: str) -> Payment | None: ...


class OutboxRepository(Protocol):
    def add(self, message: OutboxMessage) -> None: ...

    async def lock_pending(self, limit: int) -> list[OutboxMessage]: ...


class UnitOfWork(Protocol):
    payments: PaymentRepository
    outbox: OutboxRepository

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    async def __aenter__(self) -> "UnitOfWork": ...

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None: ...


class WebhookGuard(Protocol):
    def ensure(self, url: str) -> None: ...


class Gateway(Protocol):
    async def process(self, payment_id: UUID) -> bool: ...


class WebhookSender(Protocol):
    async def deliver(self, url: str, payload: dict[str, Any]) -> None: ...


class OutboxPublisher(Protocol):
    async def publish_outbox(self, payload: dict[str, Any]) -> None: ...


class AttemptPublisher(Protocol):
    async def publish_retry(self, payload: dict[str, Any], attempt: int) -> None: ...

    async def publish_dlq(self, payload: dict[str, Any], attempt: int) -> None: ...
