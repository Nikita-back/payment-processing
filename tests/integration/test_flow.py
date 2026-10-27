import pytest
from faststream.rabbit import RabbitBroker

from app.application.create_payment import CreatePayment
from app.application.get_payment import GetPayment
from app.application.process_payment import ProcessPayment
from app.application.publish_outbox import PublishOutbox
from app.infrastructure.db.engine import make_session_factory
from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from app.infrastructure.gateway import PaymentGateway
from app.infrastructure.messaging.consumer import register_consumer
from app.infrastructure.messaging.publisher import RabbitPublisher
from app.infrastructure.netpolicy import NetworkWebhookGuard
from app.infrastructure.webhook import WebhookClient
from tests.helpers import HEADERS, payment_body, payment_request, wait_for
from tests.http_probe import HttpProbe

pytestmark = pytest.mark.integration


async def _noop(_: float) -> None:
    return None


async def test_processor_decline_and_webhook_retry_over_http(engine) -> None:
    factory = make_session_factory(engine)
    uow_factory = lambda: SqlAlchemyUnitOfWork(factory)
    async with HttpProbe([500, 500, 200]) as probe:
        async with uow_factory() as uow:
            payment = await CreatePayment(
                NetworkWebhookGuard(allow_private_networks=True)
            ).execute(uow, payment_request(webhook_url=probe.url), "flow-1")
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
        await ProcessPayment(uow_factory, gateway, webhook).process(payment.id)
        async with uow_factory() as uow:
            stored = await GetPayment().execute(uow, payment.id)
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
        uow_factory = application.state.uow_factory
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
        register_consumer(broker, ProcessPayment(uow_factory, gateway, webhook), publisher)
        await broker.start()
        try:
            async with uow_factory() as uow:
                assert await PublishOutbox().run(uow, publisher, batch_size=10) == 1

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
