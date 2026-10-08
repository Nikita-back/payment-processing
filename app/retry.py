def retry_delay_ms(attempt: int, base_delay_ms: int) -> int:
    return base_delay_ms * (2**attempt)


def retry_routing_key(attempt: int) -> str:
    return f"payments.new.retry.{attempt}"


def retry_queue_name(attempt: int) -> str:
    return f"payments.new.retry.{attempt}"


def should_dead_letter(attempt: int, max_attempts: int) -> bool:
    return attempt + 1 >= max_attempts


def read_attempt(headers: dict | None) -> int:
    if not headers:
        return 0
    raw = headers.get("x-attempt", 0)
    if raw is None:
        return 0
    return int(raw)
