import secrets
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.api.schemas import PaymentAccepted, PaymentCreate, PaymentDetails
from app.application.create_payment import CreatePayment
from app.application.get_payment import GetPayment
from app.application.ports import UnitOfWork
from app.domain.payment import Payment
from app.domain.request import PaymentRequest


async def require_api_key(
    request: Request,
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    expected = request.app.state.settings.api_key
    if x_api_key is None or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid API key")


async def get_unit_of_work(request: Request):
    async with request.app.state.uow_factory() as uow:
        yield uow


def get_create_payment(request: Request) -> CreatePayment:
    return request.app.state.create_payment


def get_read_payment(request: Request) -> GetPayment:
    return request.app.state.get_payment


router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])


@router.post("/payments", status_code=202, response_model=PaymentAccepted)
async def create_payment(
    body: PaymentCreate,
    uow: Annotated[UnitOfWork, Depends(get_unit_of_work)],
    use_case: Annotated[CreatePayment, Depends(get_create_payment)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
) -> PaymentAccepted:
    payment = await use_case.execute(uow, _request(body), idempotency_key)
    return PaymentAccepted(
        payment_id=payment.id,
        status=payment.status.value,
        created_at=payment.created_at,
    )


@router.get("/payments/{payment_id}", response_model=PaymentDetails)
async def read_payment(
    payment_id: UUID,
    uow: Annotated[UnitOfWork, Depends(get_unit_of_work)],
    use_case: Annotated[GetPayment, Depends(get_read_payment)],
) -> PaymentDetails:
    payment = await use_case.execute(uow, payment_id)
    return _details(payment)


def _request(body: PaymentCreate) -> PaymentRequest:
    return PaymentRequest(
        amount=body.amount,
        currency=body.currency,
        description=body.description,
        metadata=body.metadata,
        webhook_url=str(body.webhook_url),
    )


def _details(payment: Payment) -> PaymentDetails:
    return PaymentDetails(
        payment_id=payment.id,
        amount=payment.amount,
        currency=payment.currency,
        description=payment.description,
        metadata=payment.metadata,
        status=payment.status.value,
        idempotency_key=payment.idempotency_key,
        webhook_url=payment.webhook_url,
        created_at=payment.created_at,
        processed_at=payment.processed_at,
    )
