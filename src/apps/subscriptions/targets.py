"""One key per delivery target, so spelling variants count as the same receiver.

Used to bound how many accounts can point subscriptions at one address
(``MAX_ACCOUNTS_PER_TARGET``): ``Victim+1@Example.org`` and ``victim@example.org`` are one
mailbox, ``https://hooks.example.org/in?a=1`` and ``https://HOOKS.example.org/x/../in/`` one
endpoint. Merging two real receivers only makes the cap stricter, so the keys err that way.

Keys are stored (``Subscription.target_key``). When the normalization changes, add a migration
that recomputes them, as ``0006_recompute_target_keys`` does: a stale key lets a variant in.
"""

from __future__ import annotations

import posixpath
import re
from urllib.parse import unquote, urlsplit

from apps.core.safe_http import UnsafeURLError, ascii_host, canonical_url

# Providers that ignore dots in the local part of an address.
_DOTLESS_DOMAINS = {"gmail.com": "gmail.com", "googlemail.com": "gmail.com"}


def email_key(address: str) -> str:
    local, _, domain = address.strip().rpartition("@")
    if len(local) >= 2 and local[0] == local[-1] == '"':  # "victim"@ is victim@
        local = re.sub(r"\\(.)", r"\1", local[1:-1])
    local = local.lower().split("+", 1)[0]
    try:
        domain = ascii_host(domain.strip("[]"))  # case, trailing dot, IDN -> xn--
    except UnsafeURLError:
        domain = domain.lower()
    if domain in _DOTLESS_DOMAINS:
        domain = _DOTLESS_DOMAINS[domain]
        local = local.replace(".", "")
    return f"mailto:{local}@{domain}"


def webhook_key(url: str) -> str:
    try:
        parts = urlsplit(canonical_url(url))
    except UnsafeURLError:
        return url.strip()
    return f"{parts.scheme}://{parts.netloc}{_path_key(parts.path)}"


def _path_key(path: str) -> str:
    """The path as common servers resolve it.

    Decoded once, without ``;params``, with ``\\`` as ``/``, repeated slashes collapsed, dot
    segments resolved (httpx itself sends ``/x/../in`` as ``/in``), no trailing slash, and
    case-folded (some servers ignore path case).
    """
    path = unquote(path).replace("\\", "/")
    path = re.sub(r";[^/]*", "", path)
    path = re.sub(r"/{2,}", "/", "/" + path)
    return posixpath.normpath(path).lower()


def target_key(delivery: str, target: str | None) -> str:
    if not target:
        return ""
    return email_key(target) if delivery == "email" else webhook_key(target)
