from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_serializer

Currency = Literal["RUB", "USD", "EUR"]


class PaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: Currency
    description: str = Field(default="", max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    webhook_url: AnyHttpUrl


class PaymentAccepted(BaseModel):
    payment_id: UUID
    status: str
    created_at: datetime


class PaymentDetails(BaseModel):
    payment_id: UUID
    amount: Decimal
    currency: str
    description: str
    metadata: dict[str, Any]
    status: str
    idempotency_key: str
    webhook_url: str
    created_at: datetime
    processed_at: datetime | None

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal) -> str:
        return f"{value:.2f}"
