import asyncio
from uuid import uuid4

import pytest

from app.application.create_payment import CreatePayment
from app.application.get_payment import GetPayment
from app.application.process_payment import ProcessPayment
from app.domain.errors import PaymentInProgress, PaymentNotFoundError, WebhookDeliveryError
from app.infrastructure.gateway import PaymentGateway
from tests.helpers import OpenWebhookGuard, payment_request


class ScriptedWebhook:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.calls = 0
        self.payloads: list[dict] = []

    async def deliver(self, url: str, payload: dict) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            raise WebhookDeliveryError("down")
        self.payloads.append(payload)


def gateway(success: bool) -> PaymentGateway:
    async def sleep(_: float) -> None:
        return None

    rate = 1 if success else 0
    return PaymentGateway(
        min_delay_seconds=0,
        max_delay_seconds=0,
        success_rate=rate,
        sleep=sleep,
    )


async def _payment(uow_factory):
    async with uow_factory() as uow:
        return await CreatePayment(OpenWebhookGuard()).execute(uow, payment_request(), "key-1")


async def test_success_updates_status_and_sends_webhook(uow_factory) -> None:
    payment = await _payment(uow_factory)
    webhook = ScriptedWebhook()
    processor = ProcessPayment(uow_factory, gateway(True), webhook)
    await processor.process(payment.id)
    async with uow_factory() as uow:
        stored = await GetPayment().execute(uow, payment.id)
    assert stored.status == "succeeded"
    assert stored.processed_at is not None
    assert stored.webhook_sent_at is not None
    assert webhook.payloads[0]["status"] == "succeeded"
    assert webhook.payloads[0]["payment_id"] == str(payment.id)


async def test_decline_marks_payment_failed(uow_factory) -> None:
    payment = await _payment(uow_factory)
    webhook = ScriptedWebhook()
    processor = ProcessPayment(uow_factory, gateway(False), webhook)
    await processor.process(payment.id)
    async with uow_factory() as uow:
        stored = await GetPayment().execute(uow, payment.id)
    assert stored.status == "failed"
    assert webhook.payloads[0]["status"] == "failed"


async def test_webhook_failure_does_not_repeat_gateway(uow_factory) -> None:
    payment = await _payment(uow_factory)
    calls = {"gateway": 0}

    class CountingGateway:
        async def process(self, payment_id) -> bool:
            calls["gateway"] += 1
            return True

    webhook = ScriptedWebhook(failures=1)
    processor = ProcessPayment(uow_factory, CountingGateway(), webhook)
    with pytest.raises(WebhookDeliveryError):
        await processor.process(payment.id)
    await processor.process(payment.id)
    async with uow_factory() as uow:
        stored = await GetPayment().execute(uow, payment.id)
    assert calls["gateway"] == 1
    assert stored.status == "succeeded"
    assert stored.webhook_sent_at is not None
    assert webhook.calls == 2


async def test_second_worker_does_not_call_gateway_while_claim_is_held(uow_factory) -> None:
    payment = await _payment(uow_factory)
    started = asyncio.Event()
    release = asyncio.Event()
    calls = {"gateway": 0}

    class HoldingGateway:
        async def process(self, payment_id) -> bool:
            calls["gateway"] += 1
            started.set()
            await release.wait()
            return True

    processor = ProcessPayment(uow_factory, HoldingGateway(), ScriptedWebhook(), claim_lease_seconds=30)
    first = asyncio.create_task(processor.process(payment.id))
    await started.wait()
    second = asyncio.create_task(processor.process(payment.id))
    await asyncio.sleep(0.05)
    release.set()
    done, raced = await asyncio.gather(first, second, return_exceptions=True)
    assert done is None
    assert isinstance(raced, PaymentInProgress)
    assert calls["gateway"] == 1


async def test_missing_payment_is_permanent(uow_factory) -> None:
    processor = ProcessPayment(uow_factory, gateway(True), ScriptedWebhook())
    with pytest.raises(PaymentNotFoundError):
        await processor.process(uuid4())
