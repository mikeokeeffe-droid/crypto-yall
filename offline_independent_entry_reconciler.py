"""Read-only offline reconciliation orchestration; no unlock, orders or I/O clients.

The caller must inject a separately authenticated database intent reader and
read-only exchange evidence provider. This module does NOT authenticate either
provider: fake adapters in CI demonstrate control flow, NOT real provenance.
Never use it to authorize a database transition or real entry.
"""
from dataclasses import dataclass

from entry_reconciliation_review_offline import review_persisted_entry_no_fill


@dataclass(frozen=True)
class EvidenceReview:
    status: str
    reason: str


def inspect_unresolved_entry(*, intent_reader, exchange_reader, bot, coin,
                             token, account, now_ms, max_age_ms=60_000):
    """Read intent -> fetch independent evidence -> re-read intent -> review.

    Returned status is only "hold" or "review_candidate". It is never a
    permission, proof of authentication, or a request to release anything.
    """
    def hold(reason):
        return EvidenceReview("hold", reason)

    if (bot not in ("daily", "intraday", "aggressive")
            or type(coin) is not str or not coin.isascii()
            or not coin.isalnum() or coin != coin.upper()
            or type(token) is not str or not token
            or type(account) is not str or not account.strip()
            or type(now_ms) is not int or now_ms <= 0
            or type(max_age_ms) is not int or not 0 < max_age_ms <= 300_000):
        return hold("invalid review identity or freshness configuration")

    # Never consume order/position/boolean assertions supplied by the bot.
    # All evidence must come from separately provided read-only sources.
    try:
        intent = intent_reader.read_intent(bot=bot, coin=coin, token=token)
    except Exception:
        return hold("trusted intent read unavailable")
    if type(intent) is not dict:
        return hold("durable intent unavailable")
    # Validate the exact durable identity before requesting exchange evidence.
    if (intent.get("bot") != bot or intent.get("coin") != coin
            or intent.get("token") != token
            or intent.get("status") not in ("uncertain", "submitted")
            or type(intent.get("exchange_order_id")) is not str
            or not intent["exchange_order_id"].strip()):
        return hold("durable intent cannot be matched")

    try:
        order = exchange_reader.read_order(
            account=account, order_id=intent["exchange_order_id"])
        first = exchange_reader.capture_position_orders_fills(
            account=account, coin=coin)
        second = exchange_reader.capture_position_orders_fills(
            account=account, coin=coin)
        latest_intent = intent_reader.read_intent(
            bot=bot, coin=coin, token=token)
    except Exception:
        return hold("independent evidence read failed")

    # Re-read to avoid reviewing an intent that was observably modified while
    # evidence was retrieved; this is not a transactional snapshot or fence.
    if type(latest_intent) is not dict or latest_intent != intent:
        return hold("durable intent changed during evidence review")
    for capture in (first, second):
        if type(capture) is not dict:
            return hold("exchange snapshot unavailable")
        observed = capture.get("observed_at_ms")
        if (type(observed) is not int or observed > now_ms
                or observed < now_ms - max_age_ms):
            return hold("exchange snapshot outside permitted freshness window")

    result = review_persisted_entry_no_fill(
        intent=intent, expected_bot=bot, expected_coin=coin,
        expected_token=token, expected_account=account, order=order,
        first=first, second=second)
    return EvidenceReview(result.status, result.reason)
