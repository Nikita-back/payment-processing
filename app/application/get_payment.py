from uuid import UUID

from app.application.ports import UnitOfWork
from app.domain.errors import PaymentNotFoundError
from app.domain.payment import Payment


class GetPayment:
    async def execute(self, uow: UnitOfWork, payment_id: UUID) -> Payment:
        payment = await uow.payments.get(payment_id)
        if payment is None:
            raise PaymentNotFoundError(str(payment_id))
        return payment
