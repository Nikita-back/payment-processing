import hashlib
import json
from decimal import Decimal

from app.schemas import PaymentCreate


def normalize_amount(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"))


def request_hash(body: PaymentCreate) -> str:
    payload = {
        "amount": f"{normalize_amount(body.amount):.2f}",
        "currency": body.currency,
        "description": body.description,
        "metadata": body.metadata,
        "webhook_url": str(body.webhook_url),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()
