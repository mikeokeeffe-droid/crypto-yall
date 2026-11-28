"""Strict offline JSON boundary for synthetic Hyperliquid /info payloads.

No network, exchange SDK, credentials, DB or executor imports. Parsing JSON
does not authenticate origin or prove trade/history completeness.
"""
from dataclasses import dataclass
import json


@dataclass(frozen=True)
class JsonReview:
    status: str
    reason: str
    payload: object = None


def _unique_pairs(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate JSON key")
        obj[key] = value
    return obj


def _reject_constant(value):
    raise ValueError("nonstandard JSON numeric constant")


def inspect_json_payload_offline(*, raw, kind, max_bytes=262144):
    def hold(reason):
        return JsonReview("hold", reason)
    if type(raw) is not bytes or type(max_bytes) is not int or max_bytes <= 0:
        return hold("invalid raw response or size policy")
    if not raw or len(raw) > max_bytes:
        return hold("empty or oversized response")
    if kind not in ("orderStatus", "userFillsByTime"):
        return hold("unsupported read-only response kind")
    try:
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, ValueError, TypeError, RecursionError):
        return hold("malformed or ambiguous JSON")
    if kind == "orderStatus":
        if type(payload) is not dict:
            return hold("order status response must be an object")
    elif type(payload) is not list:
        return hold("fills response must be an array")
    return JsonReview(
        "parsed_untrusted",
        "syntactic JSON only; exchange provenance and completeness unverified",
        payload,
    )
