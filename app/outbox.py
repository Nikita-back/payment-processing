import asyncio
import contextlib
import logging
from datetime import datetime, timezone

from faststream.rabbit import Channel, RabbitBroker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import Outbox
from app.publisher import RabbitPublisher
from app.topology import declare_topology

logger = logging.getLogger(__name__)


async def publish_pending(session: AsyncSession, publisher: RabbitPublisher, batch_size: int) -> int:
    statement = (
        select(Outbox)
        .where(Outbox.status == "pending")
        .order_by(Outbox.created_at)
        .limit(batch_size)
    )
    if session.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    rows = list((await session.scalars(statement)).all())
    published = 0
    for row in rows:
        try:
            await publisher.publish_outbox(row.payload)
        except Exception:
            await session.rollback()
            raise
        row.status = "published"
        row.published_at = datetime.now(timezone.utc)
        await session.commit()
        published += 1
    return published


async def run_relay(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    stop: asyncio.Event,
) -> None:
    broker = RabbitBroker(
        settings.rabbitmq_url,
        default_channel=Channel(prefetch_count=settings.consumer_prefetch, publisher_confirms=True),
        graceful_timeout=30.0,
    )
    publisher = RabbitPublisher(broker, settings.max_delivery_attempts)
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
                async with session_factory() as session:
                    await publish_pending(session, publisher, settings.outbox_batch_size)
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
