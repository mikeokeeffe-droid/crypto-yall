"""Bounded offline health gate for an already-generated report JSON snapshot.

No HTTP, Gist, secrets, exchange SDK, signer, database, subprocess, or filesystem.
This ONLY verifies report metadata is fresh and structurally complete. A PASS
never implies that the bots ran, funds are safe, or trading is authorised.
"""
from dataclasses import dataclass
import datetime as dt
import json

_EXPECTED_BOTS = frozenset(("daily", "intraday", "aggressive"))
_MAX_BYTES = 1_048_576
_MAX_FRESHNESS_SECONDS = 21_600


@dataclass(frozen=True)
class ReportHealthReview:
    status: str = "HOLD"
    reason: str = "report not independently verified"
    source_is_complete: bool = False
    report_metadata_fresh: bool = False
    publishing_approved: bool = False
    trading_approved: bool = False
    live_bots_running_verified: bool = False
    safe_to_modify_main: bool = False


def _unique_keys(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate JSON key")
        obj[key] = value
    return obj


def _reject_nonfinite(_value):
    raise ValueError("non-finite JSON number")


def inspect_report_snapshot_offline(
    payload: bytes, *, now: dt.datetime, max_age_seconds: int = 7200,
) -> ReportHealthReview:
    """Only validates a bounded snapshot; never publishes or returns its contents."""
    hold = ReportHealthReview()
    if (type(payload) is not bytes or len(payload) == 0
            or len(payload) > _MAX_BYTES
            or not isinstance(now, dt.datetime) or now.tzinfo is None
            or type(max_age_seconds) is not int
            or not 1 <= max_age_seconds <= _MAX_FRESHNESS_SECONDS):
        return hold
    try:
        report = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique_keys,
            parse_constant=_reject_nonfinite,
        )
        if type(report) is not dict:
            return hold
        stamp = dt.datetime.fromisoformat(report["generated_at"])
        if stamp.tzinfo is None:
            return hold
        stamp = stamp.astimezone(dt.timezone.utc)
        age = (now.astimezone(dt.timezone.utc) - stamp).total_seconds()
        if not 0 <= age <= max_age_seconds:
            return hold
        if (type(report.get("schema_version")) is not int
                or report["schema_version"] != 2
                or report.get("reporting_only") is not True
                or report.get("date_utc") != stamp.date().isoformat()
                or report.get("report_errors") != []):
            return hold
        bots = report.get("bots")
        if type(bots) is not dict or set(bots) != _EXPECTED_BOTS:
            return hold
        for value in bots.values():
            if (type(value) is not dict
                    or value.get("errors") != []
                    or value.get("incomplete_accounting") != []):
                return hold
        return ReportHealthReview(
            status="METADATA_PASS", reason="fresh, complete report metadata only",
            source_is_complete=True, report_metadata_fresh=True,
        )
    except (ValueError, TypeError, KeyError, OverflowError, UnicodeError):
        return hold
