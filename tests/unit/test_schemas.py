import pytest
from pydantic import ValidationError

from app.schemas import PaymentCreate, PaymentDetails
from tests.helpers import payment_body


def test_accepts_payment_body() -> None:
    from decimal import Decimal

    payment = PaymentCreate.model_validate(payment_body())
    assert payment.currency == "RUB"
    assert payment.amount == Decimal("12.30")


@pytest.mark.parametrize("currency", ["RUB", "USD", "EUR"])
def test_accepts_supported_currencies(currency: str) -> None:
    payment = PaymentCreate.model_validate(payment_body(currency=currency))
    assert payment.currency == currency


def test_rejects_oversized_metadata() -> None:
    with pytest.raises(ValidationError):
        PaymentCreate.model_validate(payment_body(metadata={"blob": "x" * 9000}))


def test_rejects_long_description() -> None:
    with pytest.raises(ValidationError):
        PaymentCreate.model_validate(payment_body(description="x" * 2001))


def test_amount_lower_bound_is_one_cent() -> None:
    from decimal import Decimal

    payment = PaymentCreate.model_validate(payment_body(amount="0.01"))
    assert payment.amount == Decimal("0.01")


@pytest.mark.parametrize(
    "overrides",
    [
        {"currency": "GBP"},
        {"currency": "rub"},
        {"amount": "0"},
        {"amount": "-1"},
        {"amount": "1.234"},
        {"webhook_url": "not-a-url"},
        {"unexpected": True},
    ],
)
def test_rejects_invalid_payment_body(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        PaymentCreate.model_validate(payment_body(**overrides))


def test_details_serialize_amount_with_two_decimals() -> None:
    from datetime import datetime, timezone
    from decimal import Decimal
    from uuid import uuid4

    details = PaymentDetails(
        payment_id=uuid4(),
        amount=Decimal("12.3"),
        currency="USD",
        description="",
        metadata={},
        status="pending",
        idempotency_key="key",
        webhook_url="https://merchant.example/hook",
        created_at=datetime.now(timezone.utc),
        processed_at=None,
    )
    assert details.model_dump(mode="json")["amount"] == "12.30"
