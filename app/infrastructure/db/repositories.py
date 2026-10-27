from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.outbox import OutboxMessage
from app.domain.payment import Payment
from app.infrastructure.db.mappers import outbox_from_row, payment_from_row, write_outbox, write_payment
from app.infrastructure.db.models import OutboxModel, PaymentModel


class SqlAlchemyPaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._payments: dict[UUID, Payment] = {}
        self._rows: dict[UUID, PaymentModel] = {}

    def add(self, payment: Payment) -> None:
        row = PaymentModel()
        write_payment(payment, row)
        self._session.add(row)
        self._payments[payment.id] = payment
        self._rows[payment.id] = row

    async def get(self, payment_id: UUID) -> Payment | None:
        return await self._load(select(PaymentModel).where(PaymentModel.id == payment_id))

    async def get_for_update(self, payment_id: UUID) -> Payment | None:
        statement = select(PaymentModel).where(PaymentModel.id == payment_id)
        if self._session.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update()
        return await self._load(statement)

    async def find_by_idempotency_key(self, key: str) -> Payment | None:
        statement = select(PaymentModel).where(PaymentModel.idempotency_key == key)
        return await self._load(statement)

    def flush(self) -> None:
        for payment_id, payment in self._payments.items():
            write_payment(payment, self._rows[payment_id])

    def clear(self) -> None:
        self._payments.clear()
        self._rows.clear()

    async def _load(self, statement) -> Payment | None:
        row = await self._session.scalar(statement)
        if row is None:
            return None
        tracked = self._payments.get(row.id)
        if tracked is not None:
            return tracked
        payment = payment_from_row(row)
        self._payments[row.id] = payment
        self._rows[row.id] = row
        return payment


class SqlAlchemyOutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._messages: dict[UUID, OutboxMessage] = {}
        self._rows: dict[UUID, OutboxModel] = {}

    def add(self, message: OutboxMessage) -> None:
        row = OutboxModel()
        write_outbox(message, row)
        self._session.add(row)
        self._messages[message.id] = message
        self._rows[message.id] = row

    async def lock_pending(self, limit: int) -> list[OutboxMessage]:
        statement = (
            select(OutboxModel)
            .where(OutboxModel.status == "pending")
            .order_by(OutboxModel.created_at)
            .limit(limit)
        )
        if self._session.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        rows = list((await self._session.scalars(statement)).all())
        messages: list[OutboxMessage] = []
        for row in rows:
            tracked = self._messages.get(row.id)
            if tracked is None:
                tracked = outbox_from_row(row)
                self._messages[row.id] = tracked
                self._rows[row.id] = row
            messages.append(tracked)
        return messages

    def flush(self) -> None:
        for message_id, message in self._messages.items():
            write_outbox(message, self._rows[message_id])

    def clear(self) -> None:
        self._messages.clear()
        self._rows.clear()
