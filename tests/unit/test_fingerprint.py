from app.fingerprint import request_hash
from app.schemas import PaymentCreate
from tests.helpers import payment_body


def test_same_payload_has_stable_hash() -> None:
    left = PaymentCreate.model_validate(payment_body(metadata={"b": 1, "a": 2}))
    right = PaymentCreate.model_validate(payment_body(metadata={"a": 2, "b": 1}))
    assert request_hash(left) == request_hash(right)


def test_different_amount_changes_hash() -> None:
    left = PaymentCreate.model_validate(payment_body(amount="10.00"))
    right = PaymentCreate.model_validate(payment_body(amount="10.01"))
    assert request_hash(left) != request_hash(right)
