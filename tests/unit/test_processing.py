from uuid import uuid4

import pytest

from app.errors import PaymentNotFoundError, WebhookDeliveryError
from app.gateway import PaymentGateway
from app.payments import create_payment, get_payment
from app.processing import PaymentProcessor
from app.schemas import PaymentCreate
from tests.helpers import payment_body


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


async def test_success_updates_status_and_sends_webhook(session_factory) -> None:
    async with session_factory() as session:
        payment = await create_payment(session, PaymentCreate.model_validate(payment_body()), "key-1")
    webhook = ScriptedWebhook()
    processor = PaymentProcessor(session_factory, gateway(True), webhook)
    await processor.process(payment.id)
    async with session_factory() as session:
        stored = await get_payment(session, payment.id)
    assert stored.status == "succeeded"
    assert stored.processed_at is not None
    assert stored.webhook_sent_at is not None
    assert webhook.payloads[0]["status"] == "succeeded"
    assert webhook.payloads[0]["payment_id"] == str(payment.id)


async def test_decline_marks_payment_failed(session_factory) -> None:
    async with session_factory() as session:
        payment = await create_payment(session, PaymentCreate.model_validate(payment_body()), "key-1")
    webhook = ScriptedWebhook()
    processor = PaymentProcessor(session_factory, gateway(False), webhook)
    await processor.process(payment.id)
    async with session_factory() as session:
        stored = await get_payment(session, payment.id)
    assert stored.status == "failed"
    assert webhook.payloads[0]["status"] == "failed"


async def test_webhook_failure_does_not_repeat_gateway(session_factory) -> None:
    async with session_factory() as session:
        payment = await create_payment(session, PaymentCreate.model_validate(payment_body()), "key-1")
    calls = {"gateway": 0}

    class CountingGateway:
        async def process(self, payment_id) -> bool:
            calls["gateway"] += 1
            return True

    webhook = ScriptedWebhook(failures=1)
    processor = PaymentProcessor(session_factory, CountingGateway(), webhook)
    with pytest.raises(WebhookDeliveryError):
        await processor.process(payment.id)
    await processor.process(payment.id)
    async with session_factory() as session:
        stored = await get_payment(session, payment.id)
    assert calls["gateway"] == 1
    assert stored.status == "succeeded"
    assert stored.webhook_sent_at is not None
    assert webhook.calls == 2


async def test_missing_payment_is_permanent(session_factory) -> None:
    processor = PaymentProcessor(session_factory, gateway(True), ScriptedWebhook())
    with pytest.raises(PaymentNotFoundError):
        await processor.process(uuid4())
