"""Offline integrity check for *synthetic* read-only /info capture fixtures.

No HTTP, exchange SDK, keys, database, privileges or production integration.
Digest matching detects a modified local fixture, not authenticated origin.
Neither a valid manifest nor parsed fills proves ownership or allows trading.
"""
from dataclasses import dataclass
import hashlib
import re
import uuid

from offline_hyperliquid_transport_plan import review_readonly_transport_plan_offline
from offline_hyperliquid_json_boundary import inspect_json_payload_offline

_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_CLOID = re.compile(r"0x[0-9a-f]{32}\Z", re.ASCII)
_FIELDS = frozenset({
    "origin", "environment", "endpoint", "method", "account", "dex",
    "request_type", "token", "fence", "cloid", "response_sha256",
    "response_bytes", "captured_at_ms", "status_code", "redirect_count",
    "transport_verified",
})


@dataclass(frozen=True)
class OfflineCaptureIntegrityReview:
    state: str
    reason: str
    response_sha256: str | None = None
    origin_authenticated: bool = False
    ownership_verified: bool = False
    submit_authorized: bool = False


def review_synthetic_info_capture(*, manifest, raw_response,
                                  expected_environment, expected_account,
                                  expected_token, expected_fence,
                                  expected_cloid, expected_request_type,
                                  now_ms):
    """Bind exact response bytes to an independently pinned *test* intent.

    All caller data remains untrusted. A review_only result means only
    fixture-internal consistency. Never promote it to authenticated evidence.
    """
    def hold(why):
        return OfflineCaptureIntegrityReview("hold", why)

    if (type(manifest) is not dict or set(manifest) != _FIELDS
            or type(raw_response) is not bytes
            or not 0 < len(raw_response) <= 262144
            or type(expected_token) is not uuid.UUID
            or type(expected_fence) is not int or expected_fence <= 0
            or type(expected_cloid) is not str
            or _CLOID.fullmatch(expected_cloid) is None
            or type(now_ms) is not int or now_ms <= 0):
        return hold("invalid synthetic capture or pinned intent")
    plan = review_readonly_transport_plan_offline(
        environment=expected_environment,
        endpoint=manifest["endpoint"],
        account=expected_account,
        expected_account=expected_account,
        dex="", method="POST",
        request_type=expected_request_type,
        allow_network=False,
    )
    if plan.status != "plan_only":
        return hold("unapproved read-only test scope")

    if (manifest["origin"] != "fixture"
            or manifest["transport_verified"] is not False
            or manifest["environment"] != expected_environment
            or manifest["account"] != expected_account
            or manifest["dex"] != ""
            or manifest["method"] != "POST"
            or manifest["request_type"] != expected_request_type
            or manifest["token"] != str(expected_token)
            or type(manifest["fence"]) is not int
            or manifest["fence"] != expected_fence
            or manifest["cloid"] != expected_cloid
            or type(manifest["status_code"]) is not int
            or manifest["status_code"] != 200
            or type(manifest["redirect_count"]) is not int
            or manifest["redirect_count"] != 0):
        return hold("fixture scope, provenance or order correlation mismatch")
    stamp = manifest["captured_at_ms"]
    if (type(stamp) is not int or stamp <= 0 or stamp > now_ms
            or now_ms - stamp > 60000):
        return hold("fixture capture timestamp missing, stale or future")
    if (type(manifest["response_bytes"]) is not int
            or manifest["response_bytes"] != len(raw_response)
            or type(manifest["response_sha256"]) is not str
            or _SHA256.fullmatch(manifest["response_sha256"]) is None):
        return hold("missing or invalid fixture body length/digest")
    digest = hashlib.sha256(raw_response).hexdigest()
    if digest != manifest["response_sha256"]:
        return hold("fixture response body changed after capture")
    parsed = inspect_json_payload_offline(raw=raw_response, kind=expected_request_type)
    if parsed.status != "parsed_untrusted":
        return hold("malformed synthetic response body")
    return OfflineCaptureIntegrityReview(
        "review_only",
        "synthetic bytes and pinned manifest agree; exchange origin, "
        "history completeness and position ownership are unverified",
        response_sha256=digest,
    )
