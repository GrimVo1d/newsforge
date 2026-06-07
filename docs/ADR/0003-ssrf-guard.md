# ADR-0003 — SSRF guard for outbound requests

**Status:** accepted (revised: the first version validated the URL, then let httpx resolve and
follow redirects on its own)

## Context

Feed URLs and webhook URLs come from users, and the worker fetches them. Without checks an
attacker can make the worker reach cloud metadata endpoints, the intranet or localhost.

Validating the URL before the request is not enough:

- httpx resolves the host again, so a DNS answer can change between check and connect
  (DNS rebinding);
- with `follow_redirects=True` a public URL can redirect to `http://169.254.169.254/`;
- block lists of private ranges miss shared address space (`100.64.0.0/10`), IPv4-mapped
  IPv6, documentation and benchmark ranges, and so on.

## Decision

All outbound requests to user-supplied URLs go through `apps.core.safe_http.request`. For
every hop it:

1. accepts only `https` (and `http` when `ALLOW_PLAIN_HTTP` is set) on the default port, with
   no credentials in the URL;
2. resolves the host once and rejects it if **any** address is not `is_global` (or is
   multicast); IPv4-mapped IPv6 addresses are checked as IPv4;
3. connects to the checked address itself, sending the original `Host` header and setting the
   TLS SNI to the hostname, so certificate verification still checks the hostname;
4. follows redirects itself (at most 5; none for webhooks), so each target goes through 1–3;
5. ignores proxy environment variables, applies one deadline to all hops and the body, and
   reads the body in chunks up to a byte limit.

`apps.feeds.validators.assert_public_url` runs the same checks when a feed or webhook URL is
saved, to reject bad input early with a `400`. The request-time check is the one that counts.

## Consequences

- No second DNS lookup, so rebinding between check and connect is not possible.
- Hosts with both public and private records are rejected.
- The worker cannot reach internal services by URL, including other compose services.
  Running a feed or webhook receiver on the internal network needs a deliberate change.
- An egress proxy (for example Smokescreen) or a network policy is still a good second layer
  in production; this guard is an application-level control.
