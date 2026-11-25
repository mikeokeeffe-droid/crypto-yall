"""Fail-closed TESTNET order *review simulator*. NOT an execution gateway.

This module is intentionally incapable of placing orders: no network, signing,
credentials, exchange SDK, file/database persistence, or command-line entrypoint.
It only validates immutable, synthetic review fixtures and simulates one-shot
claim/unknown-ack behavior in memory. A real gateway needs independent review.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

TESTNET_ENDPOINT = "https://api.hyperliquid-testnet.xyz"
TESTNET_ACCOUNT = "0xF14348Bdf59BA186F9CdD0fC5F369e1f6D3b7dC0"
REVIEW_SYMBOL = "SOL"
REVIEW_WRITER = "daily-testnet-review-fixture"
MIN_NOTIONAL = Decimal("12")
MAX_NOTIONAL = Decimal("25")
MAX_SNAPSHOT_AGE_SECONDS = 15
MAX_INTENT_TTL_SECONDS = 60


class HoldError(ValueError):
    """Any failed precondition is an unconditional HOLD, never a fallback."""


@dataclass(frozen=True)
class SyntheticIntent:
    request_id: str
    account: str
    endpoint: str
    symbol: str
    side: str
    notional_usdc: str
    leverage: int
    expires_at_s: int
    mode: str = "OFFLINE_FIXTURE_ONLY"


@dataclass(frozen=True)
class SyntheticSnapshot:
    account: str
    observed_at_s: int
    available_usdc: str
    open_order_count: int
    position_coins: tuple[str, ...]
    mode: str = "OFFLINE_FIXTURE_ONLY"


def _amount(value: str, field: str) -> Decimal:
    if type(value) is not str or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?", value):
        raise HoldError(f"HOLD: {field} must be a nonnegative decimal text value")
    try:
        num = Decimal(value)
    except InvalidOperation as exc:
        raise HoldError(f"HOLD: invalid {field}") from exc
    if not num.is_finite():
        raise HoldError(f"HOLD: invalid {field}")
    return num


def inspect_synthetic(intent: SyntheticIntent, snapshot: SyntheticSnapshot, *, now_s: int) -> str:
    """Check an offline-only review fixture. Always return a HOLD verdict."""
    if type(intent) is not SyntheticIntent or type(snapshot) is not SyntheticSnapshot:
        raise HoldError("HOLD: unexpected input types")
    if intent.mode != "OFFLINE_FIXTURE_ONLY" or snapshot.mode != "OFFLINE_FIXTURE_ONLY":
        raise HoldError("HOLD: real execution mode is forbidden")
    if intent.endpoint != TESTNET_ENDPOINT:
        raise HoldError("HOLD: endpoint is not pinned Testnet URL")
    if intent.account.lower() != TESTNET_ACCOUNT.lower() or snapshot.account.lower() != TESTNET_ACCOUNT.lower():
        raise HoldError("HOLD: incorrect Testnet account")
    if intent.symbol != REVIEW_SYMBOL or intent.side not in ("buy", "sell"):
        raise HoldError("HOLD: symbol or side is outside one-shot review scope")
    if type(intent.request_id) is not str or not re.fullmatch(r"[a-z0-9][a-z0-9-]{7,63}", intent.request_id):
        raise HoldError("HOLD: invalid request identifier")
    if type(intent.leverage) is not int or intent.leverage != 1:
        raise HoldError("HOLD: leverage must be exactly 1x")
    notional = _amount(intent.notional_usdc, "notional")
    if not MIN_NOTIONAL <= notional <= MAX_NOTIONAL:
        raise HoldError("HOLD: notional outside reviewed $12-$25 range")
    if any(type(v) is not int for v in (now_s, snapshot.observed_at_s, intent.expires_at_s)):
        raise HoldError("HOLD: timestamps must be integer seconds")
    if not 0 <= now_s - snapshot.observed_at_s <= MAX_SNAPSHOT_AGE_SECONDS:
        raise HoldError("HOLD: stale or future account snapshot")
    if not 0 < intent.expires_at_s - now_s <= MAX_INTENT_TTL_SECONDS:
        raise HoldError("HOLD: expired or unbounded one-shot request")
    if type(snapshot.open_order_count) is not int or snapshot.open_order_count != 0:
        raise HoldError("HOLD: existing or unknown open orders")
    if type(snapshot.position_coins) is not tuple or snapshot.position_coins:
        raise HoldError("HOLD: existing or unknown account positions")
    if _amount(snapshot.available_usdc, "available test balance") < notional:
        raise HoldError("HOLD: insufficient synthetic available balance")
    return "HOLD: synthetic fixture validated; network and order placement remain forbidden"


class OfflineOneShotJournal:
    """In-memory *simulation* only; not a durable cross-process mutex."""
    def __init__(self):
        self.state = "EMPTY"
        self.request_id = None
        self.writer_id = None
        self.orders_attempted = 0

    def stage(self, intent: SyntheticIntent, snapshot: SyntheticSnapshot, *, now_s: int, writer_id: str) -> str:
        if writer_id != REVIEW_WRITER:
            raise HoldError("HOLD: unauthorized synthetic writer")
        if self.state != "EMPTY":
            raise HoldError("HOLD: one-shot already consumed; replay/competing claim rejected")
        verdict = inspect_synthetic(intent, snapshot, now_s=now_s)
        self.request_id = intent.request_id
        self.writer_id = writer_id
        self.state = "STAGED_HOLD"
        # This simulator has no submit function and cannot increment attempts.
        return verdict

    def simulate_ack(self, request_id: str, outcome: str) -> str:
        if self.state != "STAGED_HOLD" or request_id != self.request_id:
            raise HoldError("HOLD: unmatched, repeated, or out-of-sequence acknowledgment")
        if outcome not in ("unknown", "filled", "rejected"):
            raise HoldError("HOLD: unrecognized acknowledgment")
        self.state = {
            "unknown": "UNKNOWN_ACK_HOLD",
            "filled": "UNVERIFIED_FILL_HOLD",
            "rejected": "UNVERIFIED_REJECTION_HOLD",
        }[outcome]
        return "HOLD: read-only independent reconciliation required; no retry"

    def reconcile_fixture(self, request_id: str, *, fresh_evidence: bool, exact_match: bool) -> str:
        if request_id != self.request_id or self.state not in (
            "UNKNOWN_ACK_HOLD", "UNVERIFIED_FILL_HOLD", "UNVERIFIED_REJECTION_HOLD"
        ):
            raise HoldError("HOLD: no matching uncertain request to reconcile")
        if type(fresh_evidence) is not bool or type(exact_match) is not bool:
            raise HoldError("HOLD: invalid synthetic reconciliation evidence")
        if not fresh_evidence or not exact_match:
            self.state = "UNRESOLVED_HOLD"
            return "HOLD: uncertain or mismatched exchange observation"
        self.state = "RECONCILED_HOLD"
        return "HOLD: synthetic reconciliation complete; one-shot remains spent"
