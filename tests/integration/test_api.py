import asyncio

import pytest
from sqlalchemy import func, select

from app.models import Outbox, Payment
from tests.helpers import HEADERS, payment_body

pytestmark = pytest.mark.integration


async def test_create_and_get_payment(api) -> None:
    client, _application = api
    created = await client.post(
        "/api/v1/payments",
        json=payment_body(),
        headers={**HEADERS, "Idempotency-Key": "api-1"},
    )
    assert created.status_code == 202
    payment_id = created.json()["payment_id"]
    fetched = await client.get(f"/api/v1/payments/{payment_id}", headers=HEADERS)
    assert fetched.status_code == 200
    assert fetched.json()["amount"] == "12.30"
    assert fetched.json()["currency"] == "RUB"
    assert fetched.json()["status"] == "pending"
    assert fetched.json()["webhook_url"] == "https://merchant.example/hook"


async def test_auth_validation_and_missing_payment(api) -> None:
    client, _application = api
    missing_key = await client.post(
        "/api/v1/payments",
        json=payment_body(),
        headers={"Idempotency-Key": "api-2"},
    )
    wrong_key = await client.get("/api/v1/payments/00000000-0000-0000-0000-000000000000", headers={"X-API-Key": "nope"})
    invalid = await client.post(
        "/api/v1/payments",
        json=payment_body(amount="-5"),
        headers={**HEADERS, "Idempotency-Key": "api-3"},
    )
    missing = await client.get("/api/v1/payments/00000000-0000-0000-0000-000000000000", headers=HEADERS)
    assert missing_key.status_code == 401
    assert wrong_key.status_code == 401
    assert invalid.status_code == 422
    assert missing.status_code == 404


async def test_idempotency_on_postgres(api) -> None:
    client, application = api
    headers = {**HEADERS, "Idempotency-Key": "api-4"}
    first = await client.post("/api/v1/payments", json=payment_body(), headers=headers)
    second = await client.post("/api/v1/payments", json=payment_body(), headers=headers)
    conflict = await client.post("/api/v1/payments", json=payment_body(currency="EUR"), headers=headers)
    assert first.json()["payment_id"] == second.json()["payment_id"]
    assert conflict.status_code == 409
    async with application.state.session_factory() as session:
        payments = await session.scalar(select(func.count()).select_from(Payment))
        outbox = await session.scalar(select(func.count()).select_from(Outbox))
    assert payments == 1
    assert outbox == 1


async def test_concurrent_create_with_one_key(api) -> None:
    client, application = api
    headers = {**HEADERS, "Idempotency-Key": "api-5"}

    async def send():
        return await client.post("/api/v1/payments", json=payment_body(), headers=headers)

    first, second = await asyncio.gather(send(), send())
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["payment_id"] == second.json()["payment_id"]
    async with application.state.session_factory() as session:
        payments = await session.scalar(select(func.count()).select_from(Payment))
        outbox = await session.scalar(select(func.count()).select_from(Outbox))
    assert payments == 1
    assert outbox == 1
