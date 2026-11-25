"""Synthetic pre-submit leverage and notional risk review. ALWAYS HOLD.

An original bot may catch a failed update_leverage() and still market_open().
A replacement sender MUST NOT use a caller's leverage confirmation as truth.
This module examines untrusted, caller-provided offline fixtures only. It
cannot attest effective leverage, account scope, fresh market price, receipt,
risk limits, exchange ownership or permission to submit. No I/O, SDK or signer.

Even perfect local arithmetic must NEVER become an order-go condition. A real
sender needs independently authenticated server-side state, atomic fencing,
risk policy, verified update outcome and separate operator authorisation.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import re

from sender_review.request_contract import inspect_sender_entry_request_offline

_NUMBER = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,8})?\Z", re.ASCII)
_MAX_DECIMAL = Decimal("100000000")
_SAMPLE_MAX_AGE_MS = 5000


@dataclass(frozen=True)
class OfflinePreSubmitRiskReview:
    state: str = "HOLD"
    reason: str = "no authenticated exchange leverage or risk evidence"
    synthetic_arithmetic_consistent: bool = False
    requested_leverage: int | None = None
    computed_notional: str | None = None
    effective_leverage_authenticated: bool = False
    market_price_authenticated: bool = False
    scope_authenticated: bool = False
    durable_fence_reserved: bool = False
    risk_budget_authorized: bool = False
    order_authorized: bool = False
    signing_enabled: bool = False


def _decimal(value):
    if type(value) is not str or _NUMBER.fullmatch(value) is None:
        return None
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or not 0 < number <= _MAX_DECIMAL:
        return None
    return number


def inspect_pre_submit_risk_fixture_offline(
    *, body, update_outcome, observed_leverage, market_price,
    max_notional, sample_time_ms, fixture_now_ms,
):
    """Compute only local diagnostic consistency; never provide trade authority.

    update_outcome is a TEST CLAIM, NOT independent exchange confirmation.
    Timings are also caller-provided. In a real service these values must be
    separately observed, authenticated and bounded behind the sole writer.
    """
    denied = OfflinePreSubmitRiskReview()
    request = inspect_sender_entry_request_offline(body=body)
    if request.state != "review_only":
        return OfflinePreSubmitRiskReview(reason="invalid-entry-intent")
    try:
        decoded = json.loads(body)
    except (TypeError, ValueError, UnicodeError):
        return denied
    if (
        type(update_outcome) is not str or update_outcome != "confirmed_fixture"
        or type(observed_leverage) is not int
        or type(decoded.get("requested_leverage")) is not int
        or observed_leverage != decoded["requested_leverage"]
        or type(sample_time_ms) is not int
        or type(fixture_now_ms) is not int
        or not 0 < sample_time_ms <= fixture_now_ms <= 9007199254740991
        or fixture_now_ms - sample_time_ms > _SAMPLE_MAX_AGE_MS
    ):
        return OfflinePreSubmitRiskReview(
            reason="failed, unknown, changed or stale leverage observation"
        )
    qty = _decimal(request.parsed_size)
    price = _decimal(market_price)
    cap = _decimal(max_notional)
    if qty is None or price is None or cap is None:
        return OfflinePreSubmitRiskReview(reason="invalid market or cap fixture")
    notional = qty * price
    if not 0 < notional <= cap:
        return OfflinePreSubmitRiskReview(
            reason="synthetic order notional exceeds fixture cap"
        )
    return OfflinePreSubmitRiskReview(
        reason="arithmetic agrees for untrusted fixtures only; "
               "exchange leverage, identity and order authority unverified",
        synthetic_arithmetic_consistent=True,
        requested_leverage=observed_leverage,
        computed_notional=format(notional, "f"),
    )
