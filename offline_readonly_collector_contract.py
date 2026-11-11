"""Offline contract for future Hyperliquid /info collector (NO NETWORK).

Pure builders and tests of caller-supplied fixture bytes. Never open HTTP,
read environment secrets, import a trading SDK, resolve DNS, sign anything,
write SQL, release a fence or infer position ownership. The operator-pinned
scope is a test input: constructing it is NOT proof of wallet ownership.
"""
from dataclasses import dataclass
import hashlib
import json
import re
import uuid

from offline_ci_info_capture_integrity import review_synthetic_info_capture

_ENDPOINTS = {
    "mainnet": "https://api.hyperliquid.xyz/info",
    "testnet": "https://api.hyperliquid-testnet.xyz/info",
}
_ACCOUNT = re.compile(r"0x[0-9a-f]{40}\Z", re.ASCII)
_CLOID = re.compile(r"0x[0-9a-f]{32}\Z", re.ASCII)
_MAX_TIME_WINDOW_MS = 3_600_000


@dataclass(frozen=True)
class OfflineCollectorScope:
    environment: str
    account: str
    token: uuid.UUID
    fence: int
    cloid: str
    dex: str = ""


@dataclass(frozen=True)
class OfflineInfoPlan:
    status: str
    reason: str
    scope: OfflineCollectorScope | None = None
    request_type: str | None = None
    endpoint: str | None = None
    request_json: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    network_authorized: bool = False


@dataclass(frozen=True)
class OfflineFixtureEnvelope:
    """Untrusted fixture capture; this class has no network source."""

    request_sha256: str
    manifest: dict
    raw_response: bytes
    network_authorized: bool = False


@dataclass(frozen=True)
class OfflineCaptureReview:
    status: str
    reason: str
    response_sha256: str | None = None
    origin_authenticated: bool = False
    history_complete: bool = False
    ownership_verified: bool = False
    submit_authorized: bool = False


def build_offline_info_plan(*, scope, request_type, start_ms=None, end_ms=None):
    """Prepare one exact read-only POST body, never send it."""
    def hold(reason):
        return OfflineInfoPlan("hold", reason)

    if (type(scope) is not OfflineCollectorScope
            or type(scope.environment) is not str
            or scope.environment not in _ENDPOINTS
            or type(scope.account) is not str
            or not _ACCOUNT.fullmatch(scope.account)
            or scope.dex != ""
            or type(scope.token) is not uuid.UUID
            or type(scope.fence) is not int or scope.fence <= 0
            or type(scope.cloid) is not str
            or not _CLOID.fullmatch(scope.cloid)):
        return hold("invalid or unpinned synthetic account/order scope")

    if request_type == "orderStatus":
        if start_ms is not None or end_ms is not None:
            return hold("orderStatus must not include fill time bounds")
        body = {"type": "orderStatus", "user": scope.account,
                "oid": scope.cloid}
    elif request_type == "userFillsByTime":
        if (type(start_ms) is not int or type(end_ms) is not int
                or start_ms <= 0 or end_ms < start_ms
                or end_ms - start_ms > _MAX_TIME_WINDOW_MS):
            return hold("invalid or unbounded inclusive fill window")
        body = {"type": "userFillsByTime", "user": scope.account,
                "startTime": start_ms, "endTime": end_ms,
                "aggregateByTime": False}
    else:
        return hold("request type not in read-only collector allowlist")

    return OfflineInfoPlan(
        status="query_only",
        reason="canonical read-only query constructed; network disabled",
        scope=scope,
        request_type=request_type,
        endpoint=_ENDPOINTS[scope.environment],
        request_json=json.dumps(body, sort_keys=True, separators=(",", ":")),
        start_ms=start_ms,
        end_ms=end_ms,
    )


def record_fixture_response_offline(*, plan, raw_response, captured_at_ms,
                                    status_code, redirect_count=0):
    """Attach local synthetic response bytes to the exact planned query.

    Values such as HTTP status and capture time are supplied by a fixture;
    they are NOT verified transport observations. Neither this method nor
    the resulting envelope performs an HTTP call.
    """
    if (type(plan) is not OfflineInfoPlan
            or plan.status != "query_only"
            or plan.network_authorized
            or plan != build_offline_info_plan(
                scope=plan.scope, request_type=plan.request_type,
                start_ms=plan.start_ms, end_ms=plan.end_ms,
            )
            or type(raw_response) is not bytes
            or not 0 < len(raw_response) <= 262144
            or type(captured_at_ms) is not int
            or type(status_code) is not int
            or type(redirect_count) is not int):
        return None

    manifest = {
        "origin": "fixture",
        "environment": plan.scope.environment,
        "endpoint": plan.endpoint,
        "method": "POST",
        "account": plan.scope.account,
        "dex": plan.scope.dex,
        "request_type": plan.request_type,
        "token": str(plan.scope.token),
        "fence": plan.scope.fence,
        "cloid": plan.scope.cloid,
        "response_sha256": hashlib.sha256(raw_response).hexdigest(),
        "response_bytes": len(raw_response),
        "captured_at_ms": captured_at_ms,
        "status_code": status_code,
        "redirect_count": redirect_count,
        "transport_verified": False,
    }
    return OfflineFixtureEnvelope(
        request_sha256=hashlib.sha256(
            plan.request_json.encode("utf-8")
        ).hexdigest(),
        manifest=manifest,
        raw_response=raw_response,
    )


def inspect_fixture_response_offline(*, plan, envelope, now_ms):
    """Check a synthetic capture; never produce an authenticated result."""
    def hold(reason):
        return OfflineCaptureReview("hold", reason)

    if (type(plan) is not OfflineInfoPlan
            or plan.status != "query_only"
            or plan.network_authorized
            or plan != build_offline_info_plan(
                scope=plan.scope, request_type=plan.request_type,
                start_ms=plan.start_ms, end_ms=plan.end_ms,
            )
            or type(envelope) is not OfflineFixtureEnvelope
            or envelope.network_authorized
            or type(envelope.request_sha256) is not str
            or envelope.request_sha256 != hashlib.sha256(
                plan.request_json.encode("utf-8")
            ).hexdigest()):
        return hold("untrusted request plan, network flag or request digest")

    checked = review_synthetic_info_capture(
        manifest=envelope.manifest,
        raw_response=envelope.raw_response,
        expected_environment=plan.scope.environment,
        expected_account=plan.scope.account,
        expected_token=plan.scope.token,
        expected_fence=plan.scope.fence,
        expected_cloid=plan.scope.cloid,
        expected_request_type=plan.request_type,
        now_ms=now_ms,
    )
    if checked.state != "review_only":
        return hold(checked.reason)
    return OfflineCaptureReview(
        "review_only",
        "synthetic request/response digests consistent only; actual transport, "
        "exchange history and position ownership unverified",
        response_sha256=checked.response_sha256,
    )
