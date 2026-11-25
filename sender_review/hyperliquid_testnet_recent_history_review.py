"""Bounded testnet recent order/fill history inspection; NO trading authority.

This module validates caller-supplied untrusted historical documents
OFFLINE only. The Boolean compatibility option is permanently inert:
there is NO HTTP transport, wallet, signer, DB or production integration.
Even internally consistent bounded records never establish ownership.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

from sender_review.hyperliquid_testnet_readonly_snapshot_review import (
    _COIN,
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
        original_size = _positive_amount(record.get("origSz"))
        if (type(record.get("timestamp")) is not int
                or not 0 <= record["timestamp"] <= 9007199254740991):
            raise ValueError("invalid historical timestamp")
        seen.add(oid)
        orders[oid] = (coin, side, item["status"], original_size)
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
        fill_size = _positive_amount(record.get("sz"))
        tids.add(tid)
        fills.setdefault(oid, []).append((coin, side, fill_size))
    return fills, len(tids)



def inspect_recent_history_documents_offline(
    *, historical_document, fills_document, start_time_ms, end_time_ms,
):
    """Inspect parsed /info documents WITHOUT network or trading authority.

    Shared by the bounded testnet reader and six-query integrated read-set.
    This cannot prove that provider history contains all earlier activity.
    """
    hold = RecentHistoryReview()
    if (type(start_time_ms) is not int or type(end_time_ms) is not int
            or not 0 <= start_time_ms < end_time_ms <= 9007199254740991
            or end_time_ms - start_time_ms > 86400000):
        return hold
    try:
        historical = _orders(historical_document)
        fills, fill_count = _fills(
            fills_document, start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
        )
        # The provider may cap/omit older records. Any unresolved order,
        # unmatched fill, overfill or partially observed filled order cannot
        # even be described as a coherent bounded order/fill sample.
        if not historical or not fills:
            return RecentHistoryReview(reason="no matching history evidence")
        if any(item[2] != "filled" for item in historical.values()):
            return RecentHistoryReview(reason="open/canceled historical order")
        # Every order marked filled must have its own matched fills inside
        # this bounded window. Otherwise a partial history can look coherent
        # because only the orders referenced by returned fills are checked.
        if set(historical) != set(fills):
            return RecentHistoryReview(
                reason="historical filled order missing matching fill records",
            )
        for oid, entries in fills.items():
            expected = historical.get(oid)
            if expected is None or expected[2] != "filled":
                return RecentHistoryReview(reason="fill lacks settled order")
            if any((coin, side) != expected[:2]
                   for coin, side, _ in entries):
                return RecentHistoryReview(reason="fill/order direction conflict")
            fill_total = sum((amount for _, _, amount in entries), Decimal("0"))
            if fill_total != expected[3]:
                # A partial result might simply be outside this bounded
                # time window. Never extrapolate a missing fill.
                return RecentHistoryReview(
                    reason="filled quantity differs from recorded original; "
                           "partial, truncated or overfilled order",
                )
        return RecentHistoryReview(
            state="RECENT_TESTNET_HISTORY_REVIEW_ONLY_HOLD",
            reason="bounded matched order/fill quantities agree; older "
                   "activity, unobserved orders and flat baseline unverified",
            recent_records_consistent=True,
            recent_order_count=len(historical),
            recent_fill_count=fill_count,
        )
    except (ValueError, TypeError, UnicodeError, OverflowError):
        return hold

def inspect_testnet_recent_history_review(
    *, configured_public_account, start_time_ms, end_time_ms,
    enabled_readonly_testnet_network=False,
):
    """Always HOLD: no network access is available via this compatibility API.

    Only inspect_recent_history_documents_offline() may review supplied
    fixtures. Reintroducing a network sender requires independent host and
    code review plus explicit separate approval.
    """
    return RecentHistoryReview()
