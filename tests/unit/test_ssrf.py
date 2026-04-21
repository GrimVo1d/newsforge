from unittest.mock import patch

import pytest

from apps.feeds.validators import SSRFError, assert_public_url


def _mock_resolve(ip: str):
    return [(0, 0, 0, "", (ip, 0))]


@patch("apps.feeds.validators.socket.getaddrinfo")
def test_rejects_localhost_ipv4(getaddr):
    getaddr.return_value = _mock_resolve("127.0.0.1")
    with pytest.raises(SSRFError):
        assert_public_url("https://localhost/feed")


@patch("apps.feeds.validators.socket.getaddrinfo")
def test_rejects_private_ipv4(getaddr):
    getaddr.return_value = _mock_resolve("10.0.0.5")
    with pytest.raises(SSRFError):
        assert_public_url("https://internal/feed")


@patch("apps.feeds.validators.socket.getaddrinfo")
def test_rejects_link_local(getaddr):
    getaddr.return_value = _mock_resolve("169.254.169.254")
    with pytest.raises(SSRFError):
        assert_public_url("https://metadata/feed")


def test_rejects_non_http_scheme():
    with pytest.raises(SSRFError):
        assert_public_url("file:///etc/passwd")


def test_rejects_plain_http_by_default():
    with pytest.raises(SSRFError):
        assert_public_url("http://example.com/feed")


@patch("apps.feeds.validators.socket.getaddrinfo")
def test_accepts_public_ip(getaddr):
    getaddr.return_value = _mock_resolve("93.184.216.34")
    assert_public_url("https://example.com/feed")
