from uuid import uuid4

from app.delivery import handle_delivery
from app.errors import PaymentNotFoundError


class Recorder:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    async def process(self, payment_id) -> None:
        self.calls += 1
        if self.error:
            raise self.error


class Publisher:
    def __init__(self) -> None:
        self.retries: list[tuple[dict, int]] = []
        self.dlq: list[tuple[dict, int]] = []

    async def publish_retry(self, payload: dict, attempt: int) -> None:
        self.retries.append((payload, attempt))

    async def publish_dlq(self, payload: dict, attempt: int) -> None:
        self.dlq.append((payload, attempt))


async def test_success_acks_without_republish() -> None:
    publisher = Publisher()
    processor = Recorder()
    payload = {"payment_id": str(uuid4())}
    await handle_delivery(payload, {"x-attempt": 0}, processor, publisher)
    assert processor.calls == 1
    assert publisher.retries == []
    assert publisher.dlq == []


async def test_transient_error_schedules_retry() -> None:
    publisher = Publisher()
    payload = {"payment_id": str(uuid4())}
    await handle_delivery(payload, {"x-attempt": 1}, Recorder(RuntimeError("down")), publisher)
    assert publisher.retries == [(payload, 1)]
    assert publisher.dlq == []


async def test_permanent_error_goes_to_dlq() -> None:
    publisher = Publisher()
    payload = {"payment_id": str(uuid4())}
    await handle_delivery(payload, None, Recorder(PaymentNotFoundError("missing")), publisher)
    assert publisher.dlq == [(payload, 1)]
    assert publisher.retries == []


async def test_unreadable_message_goes_to_dlq() -> None:
    publisher = Publisher()
    await handle_delivery({}, None, Recorder(), publisher)
    assert publisher.dlq[0][0] == {}
    assert publisher.retries == []
