"""Offline, read-only inspection of possible filled ownership recovery.

NOT a live reconciler, order submitter, or ownership authorization. Both
readers must be independently authenticated by a future trusted caller.

A pre-submit snapshot must already have been recorded durably BEFORE the
order was sent. A current exchange query cannot reconstruct past flatness.
The provided fields and freshness flags are assertions, not proven facts.
Even a handoff_candidate cannot update owned_coins, database rows, or
Hyperliquid; a separately reviewed atomic/fenced handoff is still required.
"""
from dataclasses import dataclass

from offline_filled_ownership_review import review_filled_entry_ownership


@dataclass(frozen=True)
class FilledRecoveryReview:
    status: str
    reason: str


def inspect_possible_filled_recovery(*, intent_reader, exchange_reader,
                                     bot, coin, token, account, now_ms):
    """Return 'hold' or 'handoff_candidate' from injected read-only evidence.

    Check original durable intent and recorded pre-submit capture; fetch order
    and two new exchange captures; re-read durable intent and baseline to
    catch observable changes. This does not provide a transaction or prove
    that an injected reader genuinely authenticated its sources.
    """
    def hold(reason):
        return FilledRecoveryReview("hold", reason)

    if (bot not in ("daily", "intraday", "aggressive")
            or type(coin) is not str or not coin.isascii()
            or not coin.isalnum() or coin != coin.upper()
            or type(token) is not str or not token
            or type(account) is not str or not account.strip()
            or type(now_ms) is not int or now_ms <= 0):
        return hold("invalid ownership recovery context")
    try:
        original = intent_reader.read_intent(bot=bot, coin=coin, token=token)
        if type(original) is not dict or any((
                original.get("bot") != bot, original.get("coin") != coin,
                original.get("token") != token,
                original.get("status") not in ("submitted", "uncertain"),
                original.get("action") not in ("open_long", "open_short"),
                type(original.get("exchange_order_id")) is not str,
                not original.get("exchange_order_id"),
        )):
            return hold("durable entry intent unavailable or mismatched")
        baseline = intent_reader.read_pre_submit_capture(
            bot=bot, coin=coin, token=token)
        if type(baseline) is not dict:
            return hold("recorded pre-submit baseline absent")
    except Exception:
        return hold("durable entry/baseline read failed")

    try:
        order = exchange_reader.read_order(
            account=account, order_id=original["exchange_order_id"])
        first = exchange_reader.capture_position_orders_fills(
            account=account, coin=coin)
        second = exchange_reader.capture_position_orders_fills(
            account=account, coin=coin)
        newest = intent_reader.read_intent(bot=bot, coin=coin, token=token)
        baseline_again = intent_reader.read_pre_submit_capture(
            bot=bot, coin=coin, token=token)
    except Exception:
        return hold("exchange or durable evidence read failed")
    if (type(newest) is not dict or newest != original
            or type(baseline_again) is not dict or baseline_again != baseline):
        return hold("durable entry or pre-submit baseline changed during review")

    try:
        outcome = review_filled_entry_ownership(
            intent=original, expected_bot=bot, expected_coin=coin,
            expected_token=token, expected_account=account, order=order,
            before=baseline, first=first, second=second, now_ms=now_ms)
    except Exception:
        # Unexpected evidence should never result in a handoff candidate.
        return hold("invalid or contradictory ownership evidence")
    return FilledRecoveryReview(outcome.status, outcome.reason)
