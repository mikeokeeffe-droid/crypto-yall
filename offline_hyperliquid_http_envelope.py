"""Offline-only policy for hypothetical HTTP /info transport results.

No HTTP client, networking, secrets, executors or database access. A passing
policy check means a synthetic response envelope is eligible for subsequent
read-only parsing, NOT authenticated or authorized for trading.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class HttpEnvelopeReview:
    status: str
    reason: str


MAX_RESPONSE_BYTES = 262144
MAX_ELAPSED_MS = 10000


def inspect_http_envelope_offline(*, status_code, elapsed_ms, body_bytes,
                                  redirect_count, tls_verified,
                                  expected_url, final_url, network_error=None,
                                  content_type="application/json"):
    def hold(reason):
        return HttpEnvelopeReview("hold", reason)

    if network_error is not None:
        return hold("network error or timeout")
    if type(status_code) is not int or status_code != 200:
        return hold("unexpected HTTP status or rate limit")
    if type(elapsed_ms) is not int or not 0 <= elapsed_ms <= MAX_ELAPSED_MS:
        return hold("invalid or excessive request duration")
    if type(body_bytes) is not int or not 0 <= body_bytes <= MAX_RESPONSE_BYTES:
        return hold("invalid or oversized response")
    if type(redirect_count) is not int or redirect_count != 0:
        return hold("redirect not allowed")
    if tls_verified is not True:
        return hold("TLS verification not established")
    if (type(expected_url) is not str or type(final_url) is not str
            or expected_url != final_url
            or expected_url not in (
                "https://api.hyperliquid.xyz/info",
                "https://api.hyperliquid-testnet.xyz/info",
            )):
        return hold("final origin not pinned to approved endpoint")
    if content_type != "application/json":
        return hold("unexpected response content type")
    return HttpEnvelopeReview(
        "review_only",
        "synthetic HTTP envelope passes policy; TLS and origin claims unverified",
    )
