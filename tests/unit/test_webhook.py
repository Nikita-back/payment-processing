import httpx
import pytest

from app.errors import WebhookDeliveryError
from app.webhook import WebhookClient


def scripted_transport(statuses: list[int]) -> tuple[httpx.MockTransport, list[float]]:
    delays: list[float] = []
    cursor = {"index": 0}

    def handle(request: httpx.Request) -> httpx.Response:
        status = statuses[cursor["index"]]
        cursor["index"] += 1
        return httpx.Response(status)

    return httpx.MockTransport(handle), delays


async def test_webhook_returns_on_first_success() -> None:
    transport, delays = scripted_transport([200])

    async def sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(transport=transport) as http:
        client = WebhookClient(attempts=3, base_delay_seconds=1, timeout_seconds=1, sleep=sleep, client=http)
        await client.deliver("https://merchant.example/hook", {"status": "succeeded"})
    assert delays == []


async def test_webhook_retries_with_exponential_delay() -> None:
    transport, delays = scripted_transport([500, 500, 200])

    async def sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(transport=transport) as http:
        client = WebhookClient(attempts=3, base_delay_seconds=1, timeout_seconds=1, sleep=sleep, client=http)
        await client.deliver("https://merchant.example/hook", {"status": "failed"})
    assert delays == [1, 2]


async def test_webhook_raises_after_exhausted_attempts() -> None:
    transport, delays = scripted_transport([500, 500, 500])

    async def sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(transport=transport) as http:
        client = WebhookClient(attempts=3, base_delay_seconds=0.5, timeout_seconds=1, sleep=sleep, client=http)
        with pytest.raises(WebhookDeliveryError):
            await client.deliver("https://merchant.example/hook", {"status": "failed"})
    assert delays == [0.5, 1.0]
