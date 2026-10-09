import asyncio
import logging
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

import httpx

from app.errors import WebhookDeliveryError
from app.netpolicy import assert_webhook_url

logger = logging.getLogger(__name__)


class WebhookClient:
    def __init__(
        self,
        *,
        attempts: int,
        base_delay_seconds: float,
        timeout_seconds: float,
        allow_private_networks: bool = False,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        client: httpx.AsyncClient | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._attempts = attempts
        self._base_delay = base_delay_seconds
        self._timeout = timeout_seconds
        self._allow_private_networks = allow_private_networks
        self._sleep = sleep or asyncio.sleep
        self._client = client
        self._transport = transport

    async def deliver(self, url: str, payload: dict) -> None:
        assert_webhook_url(url, allow_private_networks=self._allow_private_networks)
        client = self._client or httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=False,
            transport=self._transport,
        )
        owns_client = self._client is None
        host = urlparse(url).hostname
        try:
            for attempt in range(self._attempts):
                try:
                    response = await client.post(url, json=payload)
                    response.raise_for_status()
                    return
                except Exception:
                    logger.warning("webhook host %s failed on try %s", host, attempt + 1)
                    if attempt + 1 < self._attempts:
                        await self._sleep(self._base_delay * (2**attempt))
        finally:
            if owns_client:
                await client.aclose()
        raise WebhookDeliveryError("webhook delivery failed") from None
