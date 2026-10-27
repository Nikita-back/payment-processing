from app.domain.request import request_hash
from tests.helpers import payment_request


def test_same_payload_has_stable_hash() -> None:
    left = payment_request(metadata={"b": 1, "a": 2})
    right = payment_request(metadata={"a": 2, "b": 1})
    assert request_hash(left) == request_hash(right)


def test_different_amount_changes_hash() -> None:
    left = payment_request(amount="10.00")
    right = payment_request(amount="10.01")
    assert request_hash(left) != request_hash(right)
