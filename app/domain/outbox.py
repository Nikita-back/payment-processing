from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4


@dataclass
class OutboxMessage:
    id: UUID
    aggregate_id: UUID
    event_type: str
    payload: dict[str, Any]
    status: str
    created_at: datetime
    published_at: datetime | None = None

    @classmethod
    def for_payment(cls, payment_id: UUID, now: datetime) -> "OutboxMessage":
        return cls(
            id=uuid4(),
            aggregate_id=payment_id,
            event_type="payments.new",
            payload={"payment_id": str(payment_id)},
            status="pending",
            created_at=now,
        )

    def mark_published(self, now: datetime) -> None:
        self.status = "published"
        self.published_at = now
