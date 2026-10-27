from datetime import datetime, timezone

from app.application.ports import OutboxPublisher, UnitOfWork


class PublishOutbox:
    async def run(self, uow: UnitOfWork, publisher: OutboxPublisher, batch_size: int) -> int:
        messages = await uow.outbox.lock_pending(batch_size)
        published = 0
        for message in messages:
            try:
                await publisher.publish_outbox(message.payload)
            except Exception:
                await uow.rollback()
                raise
            message.mark_published(datetime.now(timezone.utc))
            await uow.commit()
            published += 1
        return published
