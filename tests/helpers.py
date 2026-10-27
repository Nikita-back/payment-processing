import asyncio
import time
from decimal import Decimal

from app.domain.request import PaymentRequest

HEADERS = {"X-API-Key": "test-key"}


class OpenWebhookGuard:
    def ensure(self, url: str) -> None:
        return None


def payment_request(**overrides) -> PaymentRequest:
    body = payment_body(**overrides)
    return PaymentRequest(
        amount=Decimal(str(body["amount"])),
        currency=body["currency"],
        description=body["description"],
        metadata=body["metadata"],
        webhook_url=str(body["webhook_url"]),
    )


def payment_body(**overrides) -> dict:
    payload = {
        "amount": "12.30",
        "currency": "RUB",
        "description": "Заказ 42",
        "metadata": {"order_id": "42"},
        "webhook_url": "https://merchant.example/hook",
    }
    payload.update(overrides)
    return payload


async def wait_for(predicate, timeout: float = 10.0, interval: float = 0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError("condition was not met")
