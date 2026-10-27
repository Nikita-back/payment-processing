import asyncio
import logging

from faststream import FastStream
from faststream.rabbit import Channel, RabbitBroker

from app.application.process_payment import ProcessPayment
from app.config import get_settings
from app.infrastructure.db.engine import make_engine, make_session_factory, wait_for_schema
from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from app.infrastructure.gateway import PaymentGateway
from app.infrastructure.messaging.consumer import register_consumer
from app.infrastructure.messaging.publisher import RabbitPublisher
from app.infrastructure.messaging.topology import declare_topology
from app.infrastructure.webhook import WebhookClient


async def serve() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    engine = make_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_recycle=settings.db_pool_recycle_seconds,
    )
    await wait_for_schema(engine)
    session_factory = make_session_factory(engine)
    uow_factory = lambda: SqlAlchemyUnitOfWork(session_factory)
    await declare_topology(
        settings.rabbitmq_url,
        settings.retry_base_delay_ms,
        settings.max_delivery_attempts,
    )
    broker = RabbitBroker(
        settings.rabbitmq_url,
        default_channel=Channel(
            prefetch_count=settings.consumer_prefetch,
            publisher_confirms=True,
        ),
        graceful_timeout=30.0,
    )
    publisher = RabbitPublisher(broker, settings.max_delivery_attempts)
    gateway = PaymentGateway(
        min_delay_seconds=settings.gateway_min_delay_seconds,
        max_delay_seconds=settings.gateway_max_delay_seconds,
        success_rate=settings.gateway_success_rate,
    )
    webhook = WebhookClient(
        attempts=settings.webhook_attempts,
        base_delay_seconds=settings.webhook_retry_base_seconds,
        timeout_seconds=settings.webhook_timeout_seconds,
        allow_private_networks=settings.webhook_allow_private_networks,
    )
    processor = ProcessPayment(
        uow_factory,
        gateway,
        webhook,
        claim_lease_seconds=settings.gateway_claim_lease_seconds,
    )
    register_consumer(broker, processor, publisher)
    application = FastStream(broker)
    try:
        await application.run()
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
