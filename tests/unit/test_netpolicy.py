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


def test_public_url_is_allowed() -> None:
    assert_webhook_url("https://example.com/payments/hook", allow_private_networks=False)


def test_private_url_is_allowed_when_flag_is_on() -> None:
    assert_webhook_url("http://127.0.0.1:9/hook", allow_private_networks=True)
