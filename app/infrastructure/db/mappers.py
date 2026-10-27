from decimal import Decimal

from app.domain.outbox import OutboxMessage
from app.domain.payment import Payment, PaymentStatus
from app.infrastructure.db.models import OutboxModel, PaymentModel


def payment_from_row(row: PaymentModel) -> Payment:
    amount = row.amount if isinstance(row.amount, Decimal) else Decimal(str(row.amount))
    return Payment(
        id=row.id,
        amount=amount,
        currency=row.currency,
        description=row.description,
        metadata=dict(row.payment_metadata or {}),
        status=PaymentStatus(row.status),
        idempotency_key=row.idempotency_key,
        request_hash=row.request_hash,
        webhook_url=row.webhook_url,
        created_at=row.created_at,
        processed_at=row.processed_at,
        webhook_sent_at=row.webhook_sent_at,
        gateway_claimed_at=row.gateway_claimed_at,
    )


def write_payment(payment: Payment, row: PaymentModel) -> None:
    row.id = payment.id
    row.amount = payment.amount
    row.currency = payment.currency
    row.description = payment.description
    row.payment_metadata = payment.metadata
    row.status = payment.status.value
    row.idempotency_key = payment.idempotency_key
    row.request_hash = payment.request_hash
    row.webhook_url = payment.webhook_url
    row.created_at = payment.created_at
    row.processed_at = payment.processed_at
    row.webhook_sent_at = payment.webhook_sent_at
    row.gateway_claimed_at = payment.gateway_claimed_at


def outbox_from_row(row: OutboxModel) -> OutboxMessage:
    return OutboxMessage(
        id=row.id,
        aggregate_id=row.aggregate_id,
        event_type=row.event_type,
        payload=dict(row.payload),
        status=row.status,
        created_at=row.created_at,
        published_at=row.published_at,
    )


def write_outbox(message: OutboxMessage, row: OutboxModel) -> None:
    row.id = message.id
    row.aggregate_id = message.aggregate_id
    row.event_type = message.event_type
    row.payload = message.payload
    row.status = message.status
    row.created_at = message.created_at
    row.published_at = message.published_at
