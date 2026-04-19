# ADR-0003 — SSRF guard for outbound fetches

**Status:** accepted

## Context

`POST /api/v1/feeds/` accepts a user-supplied URL. The fetcher then makes outbound HTTP. Without checks, attackers can target internal services (cloud metadata, intranet, localhost).

## Decision

Two-layer validation in `apps.feeds.validators.assert_public_url`:

1. **Scheme** must be `http` or `https`. Plain `http` is rejected unless explicitly allowed.
2. **DNS resolution**: every resolved address is rejected if any of `is_private | is_loopback | is_link_local | is_multicast | is_reserved | is_unspecified` is `True`.

`assert_public_url` runs at the boundary (serializer) AND at fetch time (fetcher), to mitigate DNS rebinding (TOCTOU).

## Residual risk

Between `getaddrinfo` and `httpx.connect`, an attacker controlling the DNS server could swap the answer. Full mitigation requires either:
- pinning the resolved IP and connecting to it directly with a `Host: ...` header, or
- routing through a separate egress proxy (e.g. Smokescreen).

We document the residual risk here and accept it for a portfolio project; production deployments should add an egress proxy.

## Consequences

- IPv6 link-local (`fe80::/10`) and unique local (`fc00::/7`) addresses are blocked.
- Hosts behind dual-stack (`A` + `AAAA`) are validated for both records.
