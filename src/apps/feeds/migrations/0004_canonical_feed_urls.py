"""Store existing feed URLs in the canonical spelling new ones get (safe_http.canonical_url).

A URL whose canonical form another feed already has is left as it is: merging two feeds
would have to move their articles and subscriptions, which is a decision for the operator.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import idna
from django.db import migrations

_DEFAULT_PORTS = {"http": 80, "https": 443}


def _canonical(url: str) -> str | None:
    try:
        parts = urlsplit(url.strip())
        port = parts.port
        host = (parts.hostname or "").rstrip(".").lower()
        if not host.isascii():
            host = idna.encode(host, uts46=True).decode("ascii")
    except (ValueError, idna.IDNAError):
        return None
    if not host:
        return None
    netloc = f"[{host}]" if ":" in host else host
    scheme = parts.scheme.lower()
    if port is not None and port != _DEFAULT_PORTS.get(scheme):
        netloc = f"{netloc}:{port}"
    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))


def _forwards(apps, schema_editor):
    Feed = apps.get_model("feeds", "Feed")
    for feed in Feed.objects.only("id", "url").iterator():
        url = _canonical(feed.url)
        if url and url != feed.url and not Feed.objects.filter(url=url).exists():
            Feed.objects.filter(pk=feed.pk).update(url=url)


class Migration(migrations.Migration):
    dependencies = [("feeds", "0003_drop_feeds_due_partial_idx")]

    operations = [migrations.RunPython(_forwards, migrations.RunPython.noop)]
