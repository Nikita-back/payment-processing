import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


def normalize_amount(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"))


@dataclass(frozen=True)
class PaymentRequest:
    amount: Decimal
    currency: str
    description: str
    metadata: dict[str, Any]
    webhook_url: str


def request_hash(body: PaymentRequest) -> str:
    payload = {
        "amount": f"{normalize_amount(body.amount):.2f}",
        "currency": body.currency,
        "description": body.description,
        "metadata": body.metadata,
        "webhook_url": body.webhook_url,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()
