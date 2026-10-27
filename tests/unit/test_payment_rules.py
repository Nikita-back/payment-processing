from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.domain.errors import IdempotencyConflictError, PaymentInProgress
from app.domain.payment import Payment, PaymentStatus
from app.domain.request import PaymentRequest


def _payment() -> Payment:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return Payment.open(
        PaymentRequest(
            amount=Decimal("10.00"),
            currency="RUB",
            description="",
            metadata={},
            webhook_url="https://merchant.example/hook",
        ),
        "key-1",
        "digest-a",
        now,
    )


def test_same_digest_is_accepted() -> None:
    payment = _payment()
    payment.ensure_same_request("digest-a")


def test_different_digest_conflicts() -> None:
    payment = _payment()
    with pytest.raises(IdempotencyConflictError):
        payment.ensure_same_request("digest-b")


def test_finish_sets_terminal_status_once() -> None:
    payment = _payment()
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    payment.finish(True, now)
    payment.finish(False, datetime(2026, 1, 3, tzinfo=timezone.utc))
    assert payment.status is PaymentStatus.SUCCEEDED
    assert payment.processed_at == now


def test_second_claim_inside_lease_is_rejected() -> None:
    payment = _payment()
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    payment.begin_processing(now, timedelta(seconds=30))
    with pytest.raises(PaymentInProgress):
        payment.begin_processing(now + timedelta(seconds=5), timedelta(seconds=30))
