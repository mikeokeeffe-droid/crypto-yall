"""Offline-only review of consecutive Hyperliquid time-window fill fixtures.

No network calls, signing, credentials, database writes or live authorization.
The result NEVER certifies complete historical exchange fills: retention,
API truncation, independently authenticated transport and exact exchange
pagination semantics remain unresolved. All candidate records are untrusted.
"""
from dataclasses import dataclass
from offline_hyperliquid_wire_review import parse_fills_by_time_offline


@dataclass(frozen=True)
class WindowAudit:
    status: str
    reason: str
    records: tuple = ()


def audit_fill_windows_offline(*, account, start_ms, end_ms, windows,
                               cap=2000, max_windows=20):
    def hold(reason):
        return WindowAudit("hold", reason)

    if (type(start_ms) is not int or type(end_ms) is not int
            or start_ms <= 0 or end_ms < start_ms
            or type(windows) is not list or not windows
            or type(max_windows) is not int or not 1 <= max_windows <= 20
            or len(windows) > max_windows):
        return hold("invalid bounded history window")
    # Hyperliquid only exposes the most recent 10,000 fills through this API.
    # At the retention boundary, earlier fills may be silently inaccessible.
    # This is an additional HOLD condition, not proof below the threshold.
    expected = start_ms
    seen = {}
    for item in windows:
        if (type(item) is not dict
                or type(item.get("start_ms")) is not int
                or type(item.get("end_ms")) is not int
                or item["start_ms"] != expected
                or item["end_ms"] < expected
                or item["end_ms"] > end_ms):
            return hold("missing, reordered or overlapping time range")
        lo, hi = item["start_ms"], item["end_ms"]
        request = item.get("request")
        response = item.get("response")
        result = parse_fills_by_time_offline(
            request=request, response=response, account=account,
            start_ms=lo, end_ms=hi, cap=cap,
        )
        if result.status != "parsed_untrusted":
            return hold("malformed, saturated or inconsistent fill window")
        for record in result.records:
            tid = record[2]
            if tid in seen:
                return hold("duplicate trade id across windows")
            seen[tid] = record
            if len(seen) >= 10000:
                return hold("10,000-fill retention boundary; older history may be missing")
        expected = hi + 1
    if expected != end_ms + 1:
        return hold("requested history window not exhausted")
    return WindowAudit(
        "parsed_untrusted",
        "time windows covered synthetically; exchange history completeness unverified",
        tuple(seen.values()),
    )
