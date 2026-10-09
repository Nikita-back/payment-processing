import pytest

from app.errors import WebhookURLRejected
from app.netpolicy import assert_webhook_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/hook",
        "http://10.1.2.3/hook",
        "http://192.168.0.5/hook",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/hook",
        "http://localhost/hook",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://user:secret@example.com/hook",
        "ftp://example.com/hook",
    ],
)
def test_private_and_credential_urls_are_rejected(url: str) -> None:
    with pytest.raises(WebhookURLRejected):
        assert_webhook_url(url, allow_private_networks=False)


def test_public_url_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.netpolicy.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    assert_webhook_url("https://example.com/payments/hook", allow_private_networks=False)


def test_hostname_that_resolves_to_private_ip_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.netpolicy.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("10.0.0.8", 0))],
    )
    with pytest.raises(WebhookURLRejected):
        assert_webhook_url("https://merchant.example/hook", allow_private_networks=False)


def test_private_url_is_allowed_when_flag_is_on() -> None:
    assert_webhook_url("http://127.0.0.1:9/hook", allow_private_networks=True)
