import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import IdempotencyConflictError, PaymentNotFoundError, WebhookURLRejected
from app.models import Payment
from app.netpolicy import assert_webhook_url
from app.payments import create_payment, get_payment
from app.schemas import PaymentAccepted, PaymentCreate, PaymentDetails


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])

    @router.post("/payments", status_code=202, response_model=PaymentAccepted)
    async def create(
        body: PaymentCreate,
        request: Request,
        session: Annotated[AsyncSession, Depends(get_session)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
    ) -> PaymentAccepted:
        key = idempotency_key.strip()
        if not key:
            raise HTTPException(status_code=400, detail="Idempotency-Key is empty")
        try:
            assert_webhook_url(
                str(body.webhook_url),
                allow_private_networks=request.app.state.settings.webhook_allow_private_networks,
            )
        except WebhookURLRejected:
            raise HTTPException(status_code=422, detail="webhook_url is not allowed") from None
        try:
            payment = await create_payment(session, body, key)
        except IdempotencyConflictError:
            raise HTTPException(
                status_code=409,
                detail="Idempotency key already used with a different request",
            ) from None
        return PaymentAccepted(
            payment_id=payment.id,
            status=payment.status,
            created_at=payment.created_at,
        )

    @router.get("/payments/{payment_id}", response_model=PaymentDetails)
    async def read(
        payment_id: UUID,
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> PaymentDetails:
        try:
            payment = await get_payment(session, payment_id)
        except PaymentNotFoundError:
            raise HTTPException(status_code=404, detail="Payment not found") from None
        return _details(payment)

    return router


async def require_api_key(
    request: Request,
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    expected = request.app.state.settings.api_key
    if x_api_key is None or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid API key")


async def get_session(request: Request):
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session


def _details(payment: Payment) -> PaymentDetails:
    return PaymentDetails(
        payment_id=payment.id,
        amount=payment.amount,
        currency=payment.currency,
        description=payment.description,
        metadata=payment.payment_metadata,
        status=payment.status,
        idempotency_key=payment.idempotency_key,
        webhook_url=payment.webhook_url,
        created_at=payment.created_at,
        processed_at=payment.processed_at,
    )
