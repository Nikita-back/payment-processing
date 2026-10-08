import ipaddress
import socket
from urllib.parse import urlparse

from app.errors import WebhookURLRejected

_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata",
        "metadata.google.internal",
    }
)


def assert_webhook_url(url: str, *, allow_private_networks: bool) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise WebhookURLRejected("webhook scheme is not allowed")
    if parsed.username or parsed.password:
        raise WebhookURLRejected("webhook credentials are not allowed")
    host = parsed.hostname
    if not host:
        raise WebhookURLRejected("webhook host is missing")
    if allow_private_networks:
        return
    if _host_is_blocked(host):
        raise WebhookURLRejected("webhook host is not allowed")


def _host_is_blocked(host: str) -> bool:
    lowered = host.lower().rstrip(".")
    if lowered in _BLOCKED_HOSTS or lowered.endswith(".local"):
        return True
    try:
        return not ipaddress.ip_address(lowered).is_global
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(lowered, None)
    except socket.gaierror:
        return False
    addresses = {item[4][0] for item in infos}
    return any(not ipaddress.ip_address(address).is_global for address in addresses)
