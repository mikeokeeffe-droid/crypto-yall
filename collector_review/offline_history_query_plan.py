"""Strict TESTNET-only query planning for later history-collector review.

NO networking or executable transport: this module only creates canonical
POST /info request bytes for OFFLINE inspection. Do not add these request
types to the existing collector entrypoint or its transport helper.

Source contracts reviewed against Hyperliquid official /info documentation:
- orderStatus: {type, user, oid} where oid is u64 or 16-byte hex CLOID.
- userFillsByTime: {type, user, startTime, endTime, aggregateByTime:false}.
- userFunding: {type, user, startTime, endTime}.
Both time endpoints are inclusive. 2,000 fill response / 10,000 recent
history limits and funding coverage CANNOT be established by a request plan.
Review rate/retention limits again before any independent network approval.

A returned plan never authenticates a public account, supplies fill evidence,
makes an exchange request, or grants trading/position/close authority.
"""
from dataclasses import dataclass
import json
import re

_ENDPOINT = "https://api.hyperliquid-testnet.xyz/info"
_ACCOUNT = re.compile(r"0x[0-9a-f]{40}\Z", re.ASCII)
_CLOID = re.compile(r"0x[0-9a-f]{32}\Z", re.ASCII)
_HISTORY_TYPES = frozenset(("orderStatus", "userFillsByTime", "userFunding"))
_WINDOW_MAX_MS = 3_600_000
_U64_MAX = (1 << 64) - 1


@dataclass(frozen=True)
class OfflineHistoryQueryScope:
    """Operator-pinned test input; not proof of account ownership."""
    account: str
    environment: str = "testnet"
    dex: str = ""


@dataclass(frozen=True)
class OfflineHistoryQueryPlan:
    state: str = "hold"
    reason: str = "history collection not approved"
    endpoint: str | None = None
    request_type: str | None = None
    request_body: bytes | None = None
    network_authorized: bool = False
    transport_verified: bool = False
    origin_authenticated: bool = False
    history_complete: bool = False
    ownership_verified: bool = False
    close_authorized: bool = False
    submit_authorized: bool = False


def plan_testnet_history_query_offline(
    *, scope, request_type, oid=None, start_ms=None, end_ms=None,
):
    """Build exact review bytes, never perform or authorize an HTTP request.

    Returns HOLD on invalid scope/extra arguments, with no request bytes.
    A 'plan_only' result is a query *description*, not clearance to collect.
    """
    held = OfflineHistoryQueryPlan()
    if (type(scope) is not OfflineHistoryQueryScope
            or type(scope.account) is not str
            or _ACCOUNT.fullmatch(scope.account) is None
            or scope.environment != "testnet"
            or scope.dex != ""
            or type(request_type) is not str
            or request_type not in _HISTORY_TYPES):
        return held

    if request_type == "orderStatus":
        if start_ms is not None or end_ms is not None:
            return held
        if type(oid) is int:
            if oid <= 0 or oid > _U64_MAX:
                return held
        elif type(oid) is str:
            if _CLOID.fullmatch(oid) is None:
                return held
        else:
            return held
        body = {"type": "orderStatus", "user": scope.account, "oid": oid}
    else:
        if (oid is not None
                or type(start_ms) is not int or type(end_ms) is not int
                or start_ms <= 0 or end_ms < start_ms
                or end_ms - start_ms > _WINDOW_MAX_MS):
            return held
        body = {
            "type": request_type,
            "user": scope.account,
            "startTime": start_ms,
            "endTime": end_ms,
        }
        if request_type == "userFillsByTime":
            # Preserve individual partial fills; aggregation loses detail.
            body["aggregateByTime"] = False
    wire = json.dumps(
        body, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    if not 0 < len(wire) <= 512:
        return held
    return OfflineHistoryQueryPlan(
        state="plan_only",
        reason="canonical review plan only; no networking, exchange "
               "provenance or history completeness",
        endpoint=_ENDPOINT,
        request_type=request_type,
        request_body=wire,
    )
