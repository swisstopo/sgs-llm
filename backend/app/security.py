"""Origin allowlist, client identity, and the optional shared key.

The endpoint is unauthenticated by design (docs/protocol.md). The shared key is off by
default and is a speed bump against blind scanners, not a security boundary: the frontend
reads it from the publicly served config.json. It has two channels because the browser
WebSocket API cannot set request headers.
"""

from __future__ import annotations

import hmac

WS_KEY_SUBPROTOCOL_PREFIX = "sgs-llm-key."


def origin_allowed(origin: str | None, allowlist: tuple[str, ...]) -> bool:
    """An empty allowlist accepts anything, which is the local-development default.

    A missing Origin header is accepted: non-browser clients (the eval harness, the
    CI smoke test's raw upgrade) do not send one, and rejecting them would fail the
    deploy gate. Origin is browser-enforced, so it stops a third-party page from
    driving the socket - it does not stop a scripted client, which is what the rate
    limits are for.
    """
    if not allowlist:
        return True
    if origin is None:
        return True
    return origin in allowlist


def client_key(forwarded_for: str | None, peer: str | None) -> str:
    """The address limits are keyed by.

    Behind CloudFront the first X-Forwarded-For entry is the viewer address. It is
    only trustworthy because the ALB admits the CloudFront prefix list alone
    (docs/deployment.md#backend-deployment) - nothing else can reach this process to
    forge the header.
    """
    if forwarded_for:
        first = forwarded_for.split(",")[0].strip()
        if first:
            return first
    return peer or "unknown"


def key_matches(expected: str, presented: str | None) -> bool:
    """Constant-time comparison; an empty `expected` means the key is disabled."""
    if not expected:
        return True
    if not presented:
        return False
    return hmac.compare_digest(expected, presented)


def key_from_subprotocols(subprotocols: list[str] | None) -> str | None:
    """Extracts the key a browser smuggled through Sec-WebSocket-Protocol."""
    for offered in subprotocols or []:
        if offered.startswith(WS_KEY_SUBPROTOCOL_PREFIX):
            return offered[len(WS_KEY_SUBPROTOCOL_PREFIX) :]
    return None
