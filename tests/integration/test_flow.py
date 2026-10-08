import pytest
from faststream.rabbit import RabbitBroker

from app.consumer import register_consumer
from app.db import make_session_factory
from app.gateway import PaymentGateway
from app.outbox import publish_pending
from app.payments import create_payment, get_payment
from app.processing import PaymentProcessor
from app.publisher import RabbitPublisher
from app.schemas import PaymentCreate
from app.webhook import WebhookClient
from tests.helpers import HEADERS, payment_body, wait_for
from tests.http_probe import HttpProbe

pytestmark = pytest.mark.integration


async def _noop(_: float) -> None:
    return None


async def test_processor_decline_and_webhook_retry_over_http(engine) -> None:
    factory = make_session_factory(engine)
    async with HttpProbe([500, 500, 200]) as probe:
        async with factory() as session:
            payment = await create_payment(
                session,
                PaymentCreate.model_validate(payment_body(webhook_url=probe.url)),
                "flow-1",
            )
        gateway = PaymentGateway(
            min_delay_seconds=0,
            max_delay_seconds=0,
            success_rate=0,
            sleep=_noop,
        )
        webhook = WebhookClient(
            attempts=3,
            base_delay_seconds=0.01,
            timeout_seconds=2,
            allow_private_networks=True,
        )
        await PaymentProcessor(factory, gateway, webhook).process(payment.id)
        async with factory() as session:
            stored = await get_payment(session, payment.id)
    assert stored.status == "failed"
    assert stored.webhook_sent_at is not None
    assert probe.calls == 3
    assert probe.payloads[-1]["status"] == "failed"
    assert probe.payloads[-1]["currency"] == "RUB"


async def test_queue_consumer_marks_success_and_calls_webhook(api, rabbitmq_url) -> None:
    client, application = api
    async with HttpProbe() as probe:
        created = await client.post(
            "/api/v1/payments",
            json=payment_body(webhook_url=probe.url),
            headers={**HEADERS, "Idempotency-Key": "flow-2"},
        )
        payment_id = created.json()["payment_id"]
        factory = application.state.session_factory
        broker = RabbitBroker(rabbitmq_url)
        publisher = RabbitPublisher(broker, max_attempts=3)
        gateway = PaymentGateway(
            min_delay_seconds=0,
            max_delay_seconds=0,
            success_rate=1,
            sleep=_noop,
        )
        webhook = WebhookClient(
            attempts=3,
            base_delay_seconds=0.01,
            timeout_seconds=2,
            allow_private_networks=True,
        )
        register_consumer(broker, PaymentProcessor(factory, gateway, webhook), publisher)
        await broker.start()
        try:
            async with factory() as session:
                assert await publish_pending(session, publisher, batch_size=10) == 1

            async def finished() -> bool:
                response = await client.get(f"/api/v1/payments/{payment_id}", headers=HEADERS)
                return response.json()["status"] == "succeeded" and len(probe.payloads) == 1

            await wait_for(finished)
        finally:
            await broker.stop()
    assert probe.payloads[0]["payment_id"] == payment_id
    assert probe.payloads[0]["amount"] == "12.30"
    fetched = await client.get(f"/api/v1/payments/{payment_id}", headers=HEADERS)
    assert fetched.json()["processed_at"] is not None
