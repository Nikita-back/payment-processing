from app.retry import read_attempt, retry_delay_ms, retry_routing_key, should_dead_letter


def test_delay_doubles_each_attempt() -> None:
    assert retry_delay_ms(0, 1000) == 1000
    assert retry_delay_ms(1, 1000) == 2000
    assert retry_delay_ms(2, 1000) == 4000


def test_dead_letter_after_third_attempt() -> None:
    assert should_dead_letter(0, 3) is False
    assert should_dead_letter(1, 3) is False
    assert should_dead_letter(2, 3) is True


def test_retry_routing_key_matches_attempt() -> None:
    assert retry_routing_key(0) == "payments.new.retry.0"
    assert retry_routing_key(1) == "payments.new.retry.1"


def test_read_attempt_defaults_to_zero() -> None:
    assert read_attempt(None) == 0
    assert read_attempt({}) == 0
    assert read_attempt({"x-attempt": "2"}) == 2
