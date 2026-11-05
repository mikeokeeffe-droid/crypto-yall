"""Pure read-only Hyperliquid /info request/response boundary for offline review.

No HTTP client, URL fetch, SDK, signing, wallet, secrets, orders, DB, or
runtime integration. The caller supplies synthetic response bytes as Python
objects. This is NOT an authenticated connection and NEVER grants permission
to release an entry fence or resume trading.
"""
from dataclasses import dataclass
import re

from offline_hyperliquid_wire_review import (
    parse_order_status_offline, parse_fills_by_time_offline,
)

_ACCOUNT = re.compile(r"0x[0-9a-fA-F]{40}\Z")


@dataclass(frozen=True)
class ReadonlyEnvelope:
    status: str
    reason: str
    request: dict | None = None
    records: tuple = ()


def _account(account):
    return type(account) is str and _ACCOUNT.fullmatch(account) is not None


def build_order_status_query_offline(*, account, oid):
    if not _account(account) or type(oid) is not int or oid <= 0:
        return ReadonlyEnvelope("hold", "invalid pinned order query")
    return ReadonlyEnvelope(
        "query_only", "unexecuted /info orderStatus query",
        {"type": "orderStatus", "user": account, "oid": oid},
    )


def build_fills_query_offline(*, account, start_ms, end_ms):
    if (not _account(account)
            or type(start_ms) is not int or type(end_ms) is not int
            or start_ms <= 0 or end_ms < start_ms):
        return ReadonlyEnvelope("hold", "invalid pinned fills query")
    return ReadonlyEnvelope(
        "query_only", "unexecuted /info userFillsByTime query",
        {"type": "userFillsByTime", "user": account,
         "startTime": start_ms, "endTime": end_ms,
         "aggregateByTime": False},
    )


def inspect_order_response_offline(*, query, response, account, coin, oid,
                                   direction, requested_size, submitted_at_ms):
    if type(query) is not ReadonlyEnvelope or query.status != "query_only":
        return ReadonlyEnvelope("hold", "missing unexecuted query")
    result = parse_order_status_offline(
        request=query.request, response=response, account=account, coin=coin,
        oid=oid, direction=direction, requested_size=requested_size,
        submitted_at_ms=submitted_at_ms,
    )
    return ReadonlyEnvelope(result.status, result.reason, query.request,
                            result.records)


def inspect_fills_response_offline(*, query, response, account,
                                   start_ms, end_ms):
    if type(query) is not ReadonlyEnvelope or query.status != "query_only":
        return ReadonlyEnvelope("hold", "missing unexecuted query")
    result = parse_fills_by_time_offline(
        request=query.request, response=response, account=account,
        start_ms=start_ms, end_ms=end_ms,
    )
    return ReadonlyEnvelope(result.status, result.reason, query.request,
                            result.records)
