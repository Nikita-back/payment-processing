from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.errors import (
    BlankIdempotencyKey,
    IdempotencyConflictError,
    PaymentNotFoundError,
    WebhookURLRejected,
)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(BlankIdempotencyKey)
    async def blank_key(request: Request, exc: BlankIdempotencyKey) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": "Idempotency-Key is empty"})

    @app.exception_handler(WebhookURLRejected)
    async def webhook_rejected(request: Request, exc: WebhookURLRejected) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": "webhook_url is not allowed"})

    @app.exception_handler(IdempotencyConflictError)
    async def conflict(request: Request, exc: IdempotencyConflictError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": "Idempotency key already used with a different request"},
        )

    @app.exception_handler(PaymentNotFoundError)
    async def missing(request: Request, exc: PaymentNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Payment not found"})
