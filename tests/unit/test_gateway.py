from uuid import uuid4

from app.gateway import PaymentGateway


class SequenceRng:
    def __init__(self, values: list[float]) -> None:
        self._values = iter(values)
        self.bounds: tuple[float, float] | None = None

    def uniform(self, low: float, high: float) -> float:
        self.bounds = (low, high)
        return next(self._values)

    def random(self) -> float:
        return next(self._values)


async def test_gateway_succeeds_below_success_rate() -> None:
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    rng = SequenceRng([3.5, 0.89])
    gateway = PaymentGateway(
        min_delay_seconds=2,
        max_delay_seconds=5,
        success_rate=0.9,
        rng=rng,
        sleep=sleep,
    )
    assert await gateway.process(uuid4()) is True
    assert delays == [3.5]
    assert rng.bounds == (2, 5)


async def test_gateway_fails_at_success_rate_boundary() -> None:
    async def sleep(_: float) -> None:
        return None

    gateway = PaymentGateway(
        min_delay_seconds=2,
        max_delay_seconds=5,
        success_rate=0.9,
        rng=SequenceRng([2, 0.9]),
        sleep=sleep,
    )
    assert await gateway.process(uuid4()) is False
