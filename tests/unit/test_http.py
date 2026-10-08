import pytest
from sqlalchemy import func, select

from app.models import Payment
from tests.helpers import HEADERS, payment_body


async def test_create_returns_accepted(client) -> None:
    response = await client.post(
        "/api/v1/payments",
        json=payment_body(),
        headers={**HEADERS, "Idempotency-Key": "key-1"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["payment_id"]
    assert body["created_at"]


async def test_get_returns_payment(client) -> None:
    created = await client.post(
        "/api/v1/payments",
        json=payment_body(),
        headers={**HEADERS, "Idempotency-Key": "key-1"},
    )
    payment_id = created.json()["payment_id"]
    response = await client.get(f"/api/v1/payments/{payment_id}", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["amount"] == "12.30"
    assert body["currency"] == "RUB"
    assert body["metadata"] == {"order_id": "42"}
    assert body["idempotency_key"] == "key-1"
    assert body["processed_at"] is None


async def test_missing_and_wrong_api_key(client) -> None:
    missing = await client.post(
        "/api/v1/payments",
        json=payment_body(),
        headers={"Idempotency-Key": "key-1"},
    )
    wrong = await client.post(
        "/api/v1/payments",
        json=payment_body(),
        headers={"X-API-Key": "other", "Idempotency-Key": "key-1"},
    )
    assert missing.status_code == 401
    assert wrong.status_code == 401


async def test_invalid_body_and_missing_idempotency_key(client) -> None:
    invalid = await client.post(
        "/api/v1/payments",
        json=payment_body(currency="GBP"),
        headers={**HEADERS, "Idempotency-Key": "key-1"},
    )
    missing_key = await client.post("/api/v1/payments", json=payment_body(), headers=HEADERS)
    assert invalid.status_code == 422
    assert missing_key.status_code == 422


async def test_idempotent_replay_and_conflict(client) -> None:
    headers = {**HEADERS, "Idempotency-Key": "key-1"}
    first = await client.post("/api/v1/payments", json=payment_body(), headers=headers)
    second = await client.post("/api/v1/payments", json=payment_body(), headers=headers)
    conflict = await client.post(
        "/api/v1/payments",
        json=payment_body(amount="80.00"),
        headers=headers,
    )
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["payment_id"] == second.json()["payment_id"]
    assert conflict.status_code == 409


async def test_unknown_payment_returns_404(client) -> None:
    response = await client.get(
        "/api/v1/payments/00000000-0000-0000-0000-000000000000",
        headers=HEADERS,
    )
    assert response.status_code == 404


@pytest.mark.parametrize("currency", ["RUB", "USD", "EUR"])
async def test_accepts_each_currency(client, currency: str) -> None:
    response = await client.post(
        "/api/v1/payments",
        json=payment_body(currency=currency),
        headers={**HEADERS, "Idempotency-Key": f"cur-{currency}"},
    )
    assert response.status_code == 202


async def test_rejects_private_webhook_and_keeps_api_key_out_of_the_body(client) -> None:
    secret = "super-secret-key"
    response = await client.post(
        "/api/v1/payments",
        json=payment_body(webhook_url="http://169.254.169.254/latest/meta-data"),
        headers={"X-API-Key": secret, "Idempotency-Key": "ssrf"},
    )
    assert response.status_code == 401
    assert secret not in response.text
    denied = await client.post(
        "/api/v1/payments",
        json=payment_body(webhook_url="http://169.254.169.254/latest/meta-data"),
        headers={**HEADERS, "Idempotency-Key": "ssrf"},
    )
    assert denied.status_code == 422
    assert "169.254.169.254" not in denied.text


async def test_get_hides_internal_columns(client) -> None:
    created = await client.post(
        "/api/v1/payments",
        json=payment_body(),
        headers={**HEADERS, "Idempotency-Key": "hidden"},
    )
    payment_id = created.json()["payment_id"]
    body = (await client.get(f"/api/v1/payments/{payment_id}", headers=HEADERS)).json()
    assert "request_hash" not in body
    assert "webhook_sent_at" not in body
    assert "gateway_claimed_at" not in body


async def test_idempotency_key_is_stored_as_data(client) -> None:
    key = "'; DROP TABLE payments;--"
    response = await client.post(
        "/api/v1/payments",
        json=payment_body(),
        headers={**HEADERS, "Idempotency-Key": key},
    )
    assert response.status_code == 202
    payment_id = response.json()["payment_id"]
    fetched = await client.get(f"/api/v1/payments/{payment_id}", headers=HEADERS)
    assert fetched.json()["idempotency_key"] == key


async def test_blank_idempotency_key_is_rejected(client) -> None:
    response = await client.post(
        "/api/v1/payments",
        json=payment_body(),
        headers={**HEADERS, "Idempotency-Key": "   "},
    )
    assert response.status_code == 400


async def test_database_outage_hides_sql(client, monkeypatch) -> None:
    from sqlalchemy.exc import OperationalError

    async def down(*args, **kwargs):
        raise OperationalError("SELECT api_key FROM secrets", {}, Exception("connection refused"))

    monkeypatch.setattr("app.api.create_payment", down)
    response = await client.post(
        "/api/v1/payments",
        json=payment_body(),
        headers={**HEADERS, "Idempotency-Key": "db-down"},
    )
    assert response.status_code == 503
    assert "SELECT" not in response.text
    assert "api_key" not in response.text
    assert response.json()["detail"] == "Service temporarily unavailable"


async def test_create_persists_single_row(client, application) -> None:
    await client.post(
        "/api/v1/payments",
        json=payment_body(),
        headers={**HEADERS, "Idempotency-Key": "key-1"},
    )
    session_factory = application.state.session_factory
    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Payment))
    assert count == 1
