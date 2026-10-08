import logging
from uuid import UUID

from app.errors import PermanentFailure
from app.processing import PaymentProcessor
from app.publisher import RabbitPublisher
from app.retry import read_attempt

logger = logging.getLogger(__name__)


async def handle_delivery(
    payload: dict,
    headers: dict | None,
    processor: PaymentProcessor,
    publisher: RabbitPublisher,
) -> None:
    attempt = read_attempt(headers)
    try:
        payment_id = UUID(str(payload["payment_id"]))
    except (KeyError, TypeError, ValueError):
        logger.error("unreadable payment message")
        await publisher.publish_dlq(payload, attempt + 1)
        return
    try:
        await processor.process(payment_id)
    except PermanentFailure:
        logger.error("permanent failure for payment %s", payment_id)
        await publisher.publish_dlq(payload, attempt + 1)
    except Exception:
        logger.exception("payment %s failed on attempt %s", payment_id, attempt)
        await publisher.publish_retry(payload, attempt)
