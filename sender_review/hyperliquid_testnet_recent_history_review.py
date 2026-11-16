"""Bounded testnet recent order/fill history inspection; NO trading authority.

This intentionally reuses the pinned HTTPS /info transport from the
read-only snapshot module. It is disabled by default and has no wallet,
signer, DB, /exchange endpoint, order dispatch or production integration.
Hyperliquid history is retention-limited. Even a consistent result cannot
attribute a legacy position, prove a flat starting balance, or allow closes.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
import ssl
import urllib.request

from sender_review.hyperliquid_testnet_readonly_snapshot_review import (
    _ACCOUNT, _COIN, _NoRedirect, _info_query,
)

_AMOUNT = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,12})?\Z", re.ASCII)
_ORDER_LIMIT = 2000
_FILL_LIMIT = 2000


@dataclass(frozen=True)
class RecentHistoryReview:
    state: str = "HOLD"
    reason: str = "read-only testnet history has not been approved"
    recent_records_consistent: bool = False
    recent_order_count: int = 0
    recent_fill_count: int = 0
    possibly_truncated: bool = True
    historical_completeness_verified: bool = False
    baseline_from_flat_verified: bool = False
    account_ownership_verified: bool = False
    bot_position_ownership_verified: bool = False
    close_authorized: bool = False
    retry_authorized: bool = False
    submit_authorized: bool = False
    signing_enabled: bool = False


def _oid(number):
    return type(number) is int and 0 < number < 2**64


def _positive_amount(raw):
    if type(raw) is not str or len(raw) > 40 or not _AMOUNT.fullmatch(raw):
        raise ValueError("invalid amount")
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise ValueError("invalid amount") from None
    if not value.is_finite() or value <= 0:
        raise ValueError("nonpositive amount")
    return value


def _orders(document):
    if type(document) is not list or len(document) >= _ORDER_LIMIT:
        raise ValueError("missing, invalid, or possibly capped order history")
    seen = set()
    orders = {}
    for item in document:
        if (type(item) is not dict or type(item.get("order")) is not dict
                or item.get("status") not in ("filled", "canceled", "open")):
            raise ValueError("unknown historical order")
        record = item["order"]
        oid, coin, side = record.get("oid"), record.get("coin"), record.get("side")
        if (not _oid(oid) or oid in seen or type(coin) is not str
                or _COIN.fullmatch(coin) is None or side not in ("A", "B")):
            raise ValueError("invalid or duplicate historical order")
        _positive_amount(record.get("origSz"))
        if (type(record.get("timestamp")) is not int
                or not 0 <= record["timestamp"] <= 9007199254740991):
            raise ValueError("invalid historical timestamp")
        seen.add(oid)
        orders[oid] = (coin, side, item["status"])
    return orders


def _fills(document, *, start_time_ms, end_time_ms):
    if type(document) is not list or len(document) >= _FILL_LIMIT:
        raise ValueError("missing, invalid, or possibly capped fill history")
    fills = {}
    tids = set()
    for record in document:
        if type(record) is not dict:
            raise ValueError("invalid fill")
        oid, tid, coin, side, stamp = (
            record.get("oid"), record.get("tid"), record.get("coin"),
            record.get("side"), record.get("time"),
        )
        if (not _oid(oid) or not _oid(tid) or tid in tids
                or type(coin) is not str or _COIN.fullmatch(coin) is None
                or side not in ("A", "B") or type(stamp) is not int
                or not start_time_ms <= stamp <= end_time_ms):
            raise ValueError("invalid, stale or duplicate fill")
        _positive_amount(record.get("sz"))
        tids.add(tid)
        fills.setdefault(oid, []).append((coin, side))
    return fills, len(tids)


def inspect_testnet_recent_history_review(
    *, configured_public_account, start_time_ms, end_time_ms,
    enabled_readonly_testnet_network=False,
):
    """Review only one bounded window. NEVER infer ownership or release HOLD."""
    hold = RecentHistoryReview()
    if (enabled_readonly_testnet_network is not True
            or type(configured_public_account) is not str
            or _ACCOUNT.fullmatch(configured_public_account) is None
            or type(start_time_ms) is not int or type(end_time_ms) is not int
            or not 0 <= start_time_ms < end_time_ms <= 9007199254740991
            or end_time_ms - start_time_ms > 86400000):
        return hold
    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        historical = _orders(_info_query(
            opener, account=configured_public_account, kind="historicalOrders",
        ))
        fills, fill_count = _fills(_info_query(
            opener, account=configured_public_account, kind="userFillsByTime",
            start_time_ms=start_time_ms, end_time_ms=end_time_ms,
        ), start_time_ms=start_time_ms, end_time_ms=end_time_ms)
        # Missing historical orders, mixed sides, or unsettled matching
        # orders prevent even a limited coherence claim.
        for oid, entries in fills.items():
            expected = historical.get(oid)
            if expected is None or expected[2] != "filled":
                raise ValueError("fill with missing or unsettled order")
            if any((coin, side) != expected[:2] for coin, side in entries):
                raise ValueError("order/fill side or coin conflict")
        return RecentHistoryReview(
            state="RECENT_TESTNET_HISTORY_REVIEW_ONLY_HOLD",
            reason="bounded order/fill shapes agree, but retention, earlier "
                   "manual activity, partial fills and baseline unverified",
            recent_records_consistent=True,
            recent_order_count=len(historical),
            recent_fill_count=fill_count,
        )
    except (ValueError, TypeError, UnicodeError, OSError, OverflowError):
        return hold
