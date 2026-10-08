import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from uuid import UUID

logger = logging.getLogger(__name__)


class PaymentGateway:
    def __init__(
        self,
        *,
        min_delay_seconds: float,
        max_delay_seconds: float,
        success_rate: float,
        rng: random.Random | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._min_delay = min_delay_seconds
        self._max_delay = max_delay_seconds
        self._success_rate = success_rate
        self._rng = rng or random.Random()
        self._sleep = sleep or asyncio.sleep

    async def process(self, payment_id: UUID) -> bool:
        delay = self._rng.uniform(self._min_delay, self._max_delay)
        await self._sleep(delay)
        succeeded = self._rng.random() < self._success_rate
        logger.info("gateway finished payment %s succeeded=%s", payment_id, succeeded)
        return succeeded
