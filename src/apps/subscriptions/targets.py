"""One key per delivery target, so spelling variants count as the same receiver.

Used to bound how many accounts can point subscriptions at one address
(``MAX_ACCOUNTS_PER_TARGET``): ``Victim+1@Example.org`` and ``victim@example.org`` are one
mailbox, ``https://hooks.example.org/in?a=1`` and ``https://HOOKS.example.org/in/`` one
endpoint.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from apps.core.safe_http import UnsafeURLError, canonical_url

# Providers that ignore dots in the local part of an address.
_DOTLESS_DOMAINS = {"gmail.com": "gmail.com", "googlemail.com": "gmail.com"}


def email_key(address: str) -> str:
    local, _, domain = address.strip().lower().rpartition("@")
    local = local.split("+", 1)[0]
    if domain in _DOTLESS_DOMAINS:
        domain = _DOTLESS_DOMAINS[domain]
        local = local.replace(".", "")
    return f"mailto:{local}@{domain}"


def webhook_key(url: str) -> str:
    try:
        parts = urlsplit(canonical_url(url))
    except UnsafeURLError:
        return url.strip()
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/') or '/'}"


def target_key(delivery: str, target: str | None) -> str:
    if not target:
        return ""
    return email_key(target) if delivery == "email" else webhook_key(target)
