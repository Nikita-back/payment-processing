import asyncio
import time

HEADERS = {"X-API-Key": "test-key"}


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
