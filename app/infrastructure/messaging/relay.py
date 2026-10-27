import asyncio
import contextlib
import logging

from faststream.rabbit import Channel, RabbitBroker

from app.application.publish_outbox import PublishOutbox
from app.config import Settings
from app.infrastructure.messaging.publisher import RabbitPublisher
from app.infrastructure.messaging.topology import declare_topology

logger = logging.getLogger(__name__)


async def run_relay(settings: Settings, uow_factory, stop: asyncio.Event) -> None:
    broker = RabbitBroker(
        settings.rabbitmq_url,
        default_channel=Channel(prefetch_count=settings.consumer_prefetch, publisher_confirms=True),
        graceful_timeout=30.0,
    )
    publisher = RabbitPublisher(broker, settings.max_delivery_attempts)
    publish = PublishOutbox()
    connected = False
    try:
        while not stop.is_set():
            try:
                if not connected:
                    await declare_topology(
                        settings.rabbitmq_url,
                        settings.retry_base_delay_ms,
                        settings.max_delivery_attempts,
                    )
                    await broker.start()
                    connected = True
                async with uow_factory() as uow:
                    await publish.run(uow, publisher, settings.outbox_batch_size)
            except Exception:
                logger.exception("outbox relay failed")
                connected = False
                with contextlib.suppress(Exception):
                    await broker.stop()
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.outbox_poll_interval_seconds)
            except TimeoutError:
                continue
    finally:
        if connected:
            with contextlib.suppress(Exception):
                await broker.stop()
