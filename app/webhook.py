import asyncio
import logging
from collections.abc import Awaitable, Callable

import httpx

from app.errors import WebhookDeliveryError

logger = logging.getLogger(__name__)


class WebhookClient:
    def __init__(
        self,
        *,
        attempts: int,
        base_delay_seconds: float,
        timeout_seconds: float,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._attempts = attempts
        self._base_delay = base_delay_seconds
        self._timeout = timeout_seconds
        self._sleep = sleep or asyncio.sleep
        self._client = client

    async def deliver(self, url: str, payload: dict) -> None:
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        owns_client = self._client is None
        last_error: Exception | None = None
        try:
            for attempt in range(self._attempts):
                try:
                    response = await client.post(url, json=payload)
                    response.raise_for_status()
                    return
                except Exception as exc:
                    last_error = exc
                    logger.warning("webhook %s failed on try %s", url, attempt + 1)
                    if attempt + 1 < self._attempts:
                        await self._sleep(self._base_delay * (2**attempt))
        finally:
            if owns_client:
                await client.aclose()
        raise WebhookDeliveryError(str(last_error)) from last_error
