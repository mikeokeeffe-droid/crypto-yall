"""OFFLINE Hyperliquid read-only collector request plan; NEVER performs HTTP.

Only the official POST /info QUERY envelopes are represented. The chosen
host/account are hard-coded, synthetic TESTNET fixtures; no credentials,
Hyperliquid SDK, network transport, GitHub Actions identity, real data, DB
access or order executor exists. The query plan is *not* a runtime client.
All decisions remain HOLD, and every authority flag is False.

Official docs (reviewed 2026-11-15):
https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api
https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
History limitations: historicalOrders max 2000; userFillsByTime max 2000
per response and a total available window of the latest 10000 fills.
This cannot be treated as historical completeness for an older position.
"""
from dataclasses import dataclass
import json
import re

_TESTNET_HOST = "api.hyperliquid-testnet.xyz"
_TEST_ACCOUNT = "0x" + "1" * 40
_INFO_PATH = "/info"
_ALLOWED_TYPES = frozenset((
    "clearinghouseState", "openOrders", "historicalOrders",
    "userFillsByTime", "orderStatus",
))
_CLOID = re.compile(r"0x[0-9a-f]{32}\Z", re.ASCII)
_RECENT_HISTORICAL_ORDERS_LIMIT = 2000
_USER_FILLS_BY_TIME_PAGE_LIMIT = 2000
_USER_FILLS_RECENT_ACCESS_LIMIT = 10000


@dataclass(frozen=True)
class ReadOnlyQueryEnvelope:
    scheme: str
    host: str
    path: str
    method: str
    content_type: str
    body_json: str
    network_request_performed: bool = False
    contains_trading_key: bool = False
    authorizes_order: bool = False


@dataclass(frozen=True)
class ReadOnlyCollectorPlan:
    state: str = "HOLD"
    reason: str = "read-only design fixture, no HTTP client or exchange proof"
    queries: tuple[ReadOnlyQueryEnvelope, ...] = ()
    history_complete: bool = False
    position_ownership_verified: bool = False
    runtime_identity_authenticated: bool = False
    exchange_transport_authenticated: bool = False
    real_readonly_service_deployed: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    retry_authorized: bool = False
    signing_enabled: bool = False


@dataclass(frozen=True)
class HistoryCoverageReview:
    state: str = "HOLD"
    reason: str = "historical completeness cannot be proven from one API read"
    possible_truncation: bool = True
    independent_archive_proven: bool = False
    ownership_verified: bool = False
    close_authorized: bool = False
    retry_authorized: bool = False


def _query(body):
    assert body["type"] in _ALLOWED_TYPES
    assert body.get("user") == _TEST_ACCOUNT
    return ReadOnlyQueryEnvelope(
        scheme="https", host=_TESTNET_HOST, path=_INFO_PATH,
        method="POST", content_type="application/json",
        body_json=json.dumps(body, sort_keys=True, separators=(",", ":")),
    )


def plan_offline_readonly_testnet_collection(
    *, account, start_time_ms, end_time_ms, optional_order_lookup=None,
):
    """Document only exact proposed requests; never execute any of them.

    Time-based userFillsByTime uses milliseconds. The planner intentionally
    cannot promise a complete older fill history, even with a very early
    start time. orderStatus accepts only a pre-selected 16-byte CLOID; the
    real sender must derive/protect that identifier independently.
    """
    hold = ReadOnlyCollectorPlan()
    if (
        type(account) is not str or account != _TEST_ACCOUNT
        or type(start_time_ms) is not int or type(end_time_ms) is not int
        or not 0 <= start_time_ms < end_time_ms <= 9007199254740991
        or (optional_order_lookup is not None and (
            type(optional_order_lookup) is not str
            or _CLOID.fullmatch(optional_order_lookup) is None
        ))
    ):
        return hold
    bodies = (
        {"type": "clearinghouseState", "user": account, "dex": ""},
        {"type": "openOrders", "user": account, "dex": ""},
        {"type": "historicalOrders", "user": account},
        {"type": "userFillsByTime", "user": account,
         "startTime": start_time_ms, "endTime": end_time_ms,
         "aggregateByTime": False},
        {"type": "clearinghouseState", "user": account, "dex": ""},
    )
    if optional_order_lookup is not None:
        bodies = bodies[:-1] + (
            {"type": "orderStatus", "user": account, "oid": optional_order_lookup},
            bodies[-1],
        )
    return ReadOnlyCollectorPlan(
        reason="synthetic-only envelopes, missing read-only transport and "
               "historical provenance; no authority",
        queries=tuple(_query(body) for body in bodies),
    )


def inspect_historical_coverage_fixture_offline(
    *, request_type, record_count, claimed_oldest_reached, claimed_full_history,
):
    """Reject any assertion that a capped REST response proves completeness.

    The caller-provided flags are intentionally NEVER trusted as evidence.
    A full page implies possible truncation; a short page still does not
    prove an initial flat position or absence of older manual activity.
    """
    if (
        type(request_type) is not str
        or request_type not in ("historicalOrders", "userFillsByTime")
        or type(record_count) is not int or record_count < 0
        or type(claimed_oldest_reached) is not bool
        or type(claimed_full_history) is not bool
    ):
        return HistoryCoverageReview(reason="invalid historical coverage fixture")
    cap = (_RECENT_HISTORICAL_ORDERS_LIMIT
           if request_type == "historicalOrders"
           else _USER_FILLS_BY_TIME_PAGE_LIMIT)
    if record_count > cap:
        return HistoryCoverageReview(reason="provider page cap exceeded; reject")
    if record_count == cap:
        return HistoryCoverageReview(
            reason="provider response at cap; truncation/pagination possible")
    return HistoryCoverageReview(
        reason="below page cap, but archive/baseline and older activity "
               "remain unverified",
        possible_truncation=False,
    )
