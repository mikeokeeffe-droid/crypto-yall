"""Offline continuity review for a future *separate* private report publisher.

Accepts already-produced private JSON snapshots solely as bytes in memory.
No network, Gist, filesystem, Git, exchange, trading, or publication.
It does NOT return the original snapshots or approve storage or deployment.
"""
from dataclasses import dataclass
import datetime as dt
import json

from sender_review.report_snapshot_health_offline import (
    _unique_keys, _reject_nonfinite, inspect_report_snapshot_offline,
)

_MAX_REPORT_BYTES = 1_048_576


@dataclass(frozen=True)
class PrivateReportHandoffReview:
    verdict: str = "HOLD"
    reason: str = "prior private state not independently established"
    metadata_current: bool = False
    history_continuity_verified: bool = False
    private_destination_verified: bool = False
    publishing_authorized: bool = False
    trading_authorized: bool = False
    source_workspace_unmodified_proven: bool = False


def _parsed_report(data):
    if type(data) is not bytes or not 0 < len(data) <= _MAX_REPORT_BYTES:
        raise ValueError("invalid private report length")
    obj = json.loads(
        data.decode("utf-8"),
        object_pairs_hook=_unique_keys,
        parse_constant=_reject_nonfinite,
    )
    if type(obj) is not dict:
        raise ValueError("invalid private report shape")
    return obj


def _timestamp(raw):
    if type(raw) is not str:
        raise ValueError("missing timestamp")
    value = dt.datetime.fromisoformat(raw)
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(dt.timezone.utc)


def _tracking_started(report):
    short = report.get("short_opportunity_check")
    if type(short) is not dict:
        raise ValueError("tracking state missing")
    started = _timestamp(short.get("tracking_started_at"))
    updated = _timestamp(short.get("updated_at"))
    if updated < started:
        raise ValueError("invalid tracked interval")
    if type(short.get("bots")) is not dict:
        raise ValueError("shadow bot states absent")
    if type(short.get("dual_short_confirmed_filter")) is not dict:
        raise ValueError("filter history absent")
    return started, updated


def _retains_closed_history(old_rows, new_rows):
    """Check that older closed records survive ordinary append/200-row trim.

    A 200-row cap permits dropping the oldest rows. A no-overlap transition
    stays HOLD rather than guessing that 200+ new rows arrived at once.
    Record equality is a SYNTHETIC continuity check, not proof of provenance.
    """
    if (type(old_rows) is not list or type(new_rows) is not list
            or len(old_rows) > 200 or len(new_rows) > 200
            or any(type(row) is not dict for row in old_rows + new_rows)):
        return False
    if not old_rows:
        return True
    overlap = next(
        (n for n in range(min(len(old_rows), len(new_rows)), 0, -1)
         if old_rows[-n:] == new_rows[:n]),
        0,
    )
    return overlap > 0 and (overlap == len(old_rows) or len(new_rows) == 200)


def _check_shadow_cohorts(old_shadow, new_shadow):
    expected = {"intraday", "aggressive"}
    for filtered in (False, True):
        if filtered:
            old_part = old_shadow.get("dual_short_confirmed_filter")
            new_part = new_shadow.get("dual_short_confirmed_filter")
        else:
            old_part, new_part = old_shadow, new_shadow
        if type(old_part) is not dict or type(new_part) is not dict:
            return False
        old_bots = old_part.get("bots")
        new_bots = new_part.get("bots")
        if (type(old_bots) is not dict or type(new_bots) is not dict
                or set(old_bots) != expected or set(new_bots) != expected):
            return False
        for bot in expected:
            prior = old_bots[bot]
            candidate = new_bots[bot]
            if type(prior) is not dict or type(candidate) is not dict:
                return False
            if not _retains_closed_history(
                prior.get("closed_trades"), candidate.get("closed_trades")
            ):
                return False
    return True


def review_private_report_handoff_offline(
    *, previous: bytes, candidate: bytes, now: dt.datetime,
) -> PrivateReportHandoffReview:
    """Check metadata and prior shadow-state identity; NEVER approve publication."""
    hold = PrivateReportHandoffReview()
    if (type(now) is not dt.datetime or now.tzinfo is None
            or inspect_report_snapshot_offline(
                candidate, now=now
            ).status != "METADATA_PASS"):
        return hold
    try:
        old = _parsed_report(previous)
        new = _parsed_report(candidate)
        if (old.get("schema_version") != 2
                or old.get("reporting_only") is not True
                or type(old.get("bots")) is not dict):
            return hold
        old_stamp = _timestamp(old.get("generated_at"))
        new_stamp = _timestamp(new.get("generated_at"))
        old_start, old_update = _tracking_started(old)
        new_start, new_update = _tracking_started(new)
        if (new_stamp <= old_stamp
                or new_start != old_start
                or new_update <= old_update
                or new_update > new_stamp
                or old_update > old_stamp):
            return hold
        old_shadow = old["short_opportunity_check"]
        new_shadow = new["short_opportunity_check"]
        if (set(old_shadow["bots"]) != set(new_shadow["bots"])
                or set(old_shadow["dual_short_confirmed_filter"].get("bots", {}))
                != set(new_shadow["dual_short_confirmed_filter"].get("bots", {}))):
            return hold
        if not _check_shadow_cohorts(old_shadow, new_shadow):
            return hold
        # The sequence comparison catches obvious loss or rewrite of prior
        # paper records. It is NOT authenticated storage, history provenance,
        # an atomic compare-and-swap, or a reason to publish private reports.
        return PrivateReportHandoffReview(
            verdict="CONTINUITY_METADATA_ONLY_HOLD",
            reason="snapshot timestamps and shadow cohort identities match; private storage unverified",
            metadata_current=True,
        )
    except (ValueError, TypeError, KeyError, OverflowError, UnicodeError):
        return hold
