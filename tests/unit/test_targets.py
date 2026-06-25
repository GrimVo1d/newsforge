from __future__ import annotations

import pytest

from apps.subscriptions.targets import email_key, target_key, webhook_key


@pytest.mark.parametrize(
    ("address", "key"),
    [
        ("Victim@Example.org", "mailto:victim@example.org"),
        (" victim+news@example.org ", "mailto:victim@example.org"),
        ("first.last@example.org", "mailto:first.last@example.org"),
        ("First.Last+x@googlemail.com", "mailto:firstlast@gmail.com"),
        ('"victim"@example.org', "mailto:victim@example.org"),
        ('"v\\ictim"@example.org', "mailto:victim@example.org"),
        ("victim@Exämple.org.", "mailto:victim@xn--exmple-cua.org"),
        ("victim@xn--exmple-cua.org", "mailto:victim@xn--exmple-cua.org"),
    ],
)
def test_email_key(address, key):
    assert email_key(address) == key


@pytest.mark.parametrize(
    ("url", "key"),
    [
        ("https://Hooks.Example.org/in/?a=1#x", "https://hooks.example.org/in"),
        ("https://hooks.example.org:443/", "https://hooks.example.org/"),
        ("https://hooks.example.org", "https://hooks.example.org/"),
        ("https://hooks.example.org/In", "https://hooks.example.org/in"),
        ("https://hooks.example.org/x/../in", "https://hooks.example.org/in"),
        ("https://hooks.example.org/a/b/../../in/.", "https://hooks.example.org/in"),
        ("https://hooks.example.org/./in", "https://hooks.example.org/in"),
        ("https://hooks.example.org//in", "https://hooks.example.org/in"),
        ("https://hooks.example.org/%69n", "https://hooks.example.org/in"),
        ("https://hooks.example.org/%2e%2e/in", "https://hooks.example.org/in"),
        ("https://hooks.example.org/in;x=1", "https://hooks.example.org/in"),
        ("https://hooks.example.org/x\\..\\in", "https://hooks.example.org/in"),
        ("https://hooks.example.org/../..", "https://hooks.example.org/"),
    ],
)
def test_webhook_key(url, key):
    assert webhook_key(url) == key


def test_empty_target_has_no_key():
    assert target_key("email", "") == target_key("webhook", None) == ""
