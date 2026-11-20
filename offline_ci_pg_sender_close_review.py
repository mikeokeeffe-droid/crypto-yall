"""CI-only close review for the disposable PostgreSQL sender journal.

Even a complete synthetic match cannot authorize a close: no independent
Hyperliquid position/ownership proof exists. No signer, network, exchange SDK
or live bot. The reviewer must be read-only and must never call a close RPC.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import os
import uuid

from offline_ci_pg_sender_reconciliation import review_sender_fake_evidence


@dataclass(frozen=True)
class OfflineCloseDecision:
    state: str
    reason: str
    structurally_consistent: bool = False
    submit_authorized: bool = False
    ownership_verified: bool = False


def _positive(raw):
    if type(raw) is not str or not raw or raw.strip() != raw:
        return None
    try:
        result = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() and result > 0 else None


def review_sender_close_offline(*, reviewer_connection_factory, token, fence,
                                expected_bot, expected_account, expected_coin,
                                evidence, close_request):
    """Return HOLD only. Do not mistake synthetic consistency for ownership."""
    def hold(reason, coherent=False):
        return OfflineCloseDecision("hold", reason, coherent)

    if (os.environ.get("ISOLATED_POSTGRES_CI") != "1"
            or os.environ.get("PGDATABASE") != "safety_test"
            or os.environ.get("PGHOST") not in ("localhost", "127.0.0.1")
            or type(token) is not uuid.UUID
            or type(fence) is not int or fence <= 0
            or expected_bot not in ("daily", "intraday", "aggressive")
            or type(expected_account) is not str
            or type(expected_coin) is not str
            or not callable(reviewer_connection_factory)
            or type(close_request) is not dict
            or set(close_request) != {
                "bot", "account", "coin", "side", "close_size",
                "reduce_only", "snapshot_source",
            }):
        return hold("invalid or untrusted close-review context")

    if (close_request["bot"] != expected_bot
            or close_request["account"] != expected_account
            or close_request["coin"] != expected_coin
            or close_request["side"] not in ("long", "short")
            or close_request["reduce_only"] is not True
            or close_request["snapshot_source"] != "fixture"):
        return hold("close identity, provenance or reduce-only requirement failed")

    size = _positive(close_request["close_size"])
    if size is None:
        return hold("invalid close quantity")

    # First verify synthetic order/fill structure against the immutable
    # PostgreSQL journal, without modifying or releasing anything.
    inspection = review_sender_fake_evidence(
        reviewer_connection_factory=reviewer_connection_factory,
        token=token, fence=fence, evidence=evidence,
    )
    if not inspection.structurally_consistent:
        return hold("unverified original entry or fill evidence")

    try:
        with reviewer_connection_factory() as conn:
            if conn.info.host not in ("localhost", "127.0.0.1", "::1"):
                return hold("nonlocal reviewer database")
            who = conn.execute(
                "select current_database(),session_user,current_user"
            ).fetchone()
            if who != ("safety_test","ci_sender_reviewer","ci_sender_reviewer"):
                return hold("incorrect reviewer principal")
            row = conn.execute(
                "select bot,effective_account,coin,action,requested_size,state "
                "from public.ci_sender_intents "
                "where token=%s and fence_token=%s", (token, fence),
            ).fetchone()
    except Exception:
        return hold("sender journal unavailable")

    if row is None:
        return hold("missing sender journal intent")
    bot, account, coin, action, requested, state = row
    side = "long" if action == "open_long" else "short"
    if (bot != expected_bot or account != expected_account
            or coin != expected_coin or side != close_request["side"]
            or state != "dispatch_unknown"
            or size > requested):
        return hold("close would exceed or conflict with recorded entry")

    return hold(
        "structural match only; synthetic fills cannot establish exclusive "
        "position ownership or authorize reduce-only exchange closure",
        coherent=True,
    )
