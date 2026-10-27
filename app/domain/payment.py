from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from app.domain.errors import IdempotencyConflictError, PaymentInProgress
from app.domain.request import PaymentRequest, normalize_amount


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class ProcessingStep:
    needs_gateway: bool
    webhook_url: str | None
    payload: dict[str, Any] | None


@dataclass
class Payment:
    id: UUID
    amount: Decimal
    currency: str
    description: str
    metadata: dict[str, Any]
    status: PaymentStatus
    idempotency_key: str
    request_hash: str
    webhook_url: str
    created_at: datetime
    processed_at: datetime | None = None
    webhook_sent_at: datetime | None = None
    gateway_claimed_at: datetime | None = None

    @classmethod
    def open(
        cls,
        request: PaymentRequest,
        idempotency_key: str,
        digest: str,
        now: datetime,
    ) -> "Payment":
        return cls(
            id=uuid4(),
            amount=normalize_amount(request.amount),
            currency=request.currency,
            description=request.description,
            metadata=dict(request.metadata),
            status=PaymentStatus.PENDING,
            idempotency_key=idempotency_key,
            request_hash=digest,
            webhook_url=request.webhook_url,
            created_at=now,
        )

    def ensure_same_request(self, digest: str) -> None:
        if self.request_hash != digest:
            raise IdempotencyConflictError(self.idempotency_key)

    def begin_processing(self, now: datetime, lease: timedelta) -> ProcessingStep:
        if self.webhook_sent_at is not None:
            return ProcessingStep(False, None, None)
        if self.status != PaymentStatus.PENDING:
            return ProcessingStep(False, self.webhook_url, self.notification())
        claimed_at = _aware(self.gateway_claimed_at)
        if claimed_at is not None and now - claimed_at < lease:
            raise PaymentInProgress(str(self.id))
        self.gateway_claimed_at = now
        return ProcessingStep(True, None, None)

    def release_claim(self) -> None:
        if self.status == PaymentStatus.PENDING:
            self.gateway_claimed_at = None

    def finish(self, succeeded: bool, now: datetime) -> None:
        if self.status != PaymentStatus.PENDING:
            return
        self.status = PaymentStatus.SUCCEEDED if succeeded else PaymentStatus.FAILED
        self.processed_at = now

    def mark_notified(self, now: datetime) -> None:
        self.webhook_sent_at = now

    def notification(self) -> dict[str, Any]:
        processed_at = self.processed_at.isoformat() if self.processed_at else None
        return {
            "payment_id": str(self.id),
            "status": self.status.value,
            "amount": f"{self.amount:.2f}",
            "currency": self.currency,
            "description": self.description,
            "metadata": self.metadata,
            "processed_at": processed_at,
        }


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
