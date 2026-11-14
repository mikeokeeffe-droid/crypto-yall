"""Offline-only classification of ALL original three-bot trade mutations.

This deliberately does not implement an order sender or authorize a trade.
For new entry decisions, reuse the existing request-only CI protocol. For
pyramids, leverage mutation, and any close, return HOLD pending separate
ownership, bounded reduce-only sizing, and protective-exit reviews.

Pure Python: no exchange SDK, imports of original executors, signer, socket,
database, network, access token or environment variable.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

from offline_original_bot_intent_adapter import (
    prepare_signer_free_entry_handoff_offline,
)

_BOTS = frozenset(("daily", "intraday", "aggressive"))
_COIN = re.compile(r"[A-Z0-9]+\Z", re.ASCII)
_QUANTITY = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z", re.ASCII)


@dataclass(frozen=True)
class OfflineMutationReview:
    state: str = "hold"
    action_class: str = "unrecognized"
    reason: str = "unreviewed original bot mutation"
    request_json: str | None = None
    submit_authorized: bool = False
    ownership_verified: bool = False
    close_authorized: bool = False


def _positive_decimal(value):
    if type(value) is not str or _QUANTITY.fullmatch(value) is None:
        return False
    try:
        v = Decimal(value)
        return v.is_finite() and v > 0
    except InvalidOperation:
        return False


def review_original_bot_mutation_offline(
    *, verified_bot, trade, rounded_size, pinned_environment,
    pinned_account, pinned_dex="",
):
    """Classify a proposed original bot action; never provide execution rights.

    The pinned identity/scope is a test-harness assertion, not genuine service
    authentication. Non-entry trade payloads never go on the wire. The
    original bots retain their exact existing strategy/exit behavior.
    """
    if (type(verified_bot) is not str or verified_bot not in _BOTS
            or type(trade) is not dict
            or type(pinned_environment) is not str
            or pinned_environment not in ("mainnet", "testnet")
            or type(pinned_account) is not str
            or re.fullmatch(r"0x[0-9a-f]{40}", pinned_account) is None
            or pinned_dex != ""
            or any(key in trade for key in (
                "bot", "account", "environment", "dex", "cloid",
                "token", "private_key", "submit_authorized",
            ))
            or type(trade.get("hl_coin")) is not str
            or _COIN.fullmatch(trade["hl_coin"]) is None):
        return OfflineMutationReview(reason="unverified bot, scope or action payload")

    action = trade.get("action")
    if action in ("open_long", "open_short"):
        result = prepare_signer_free_entry_handoff_offline(
            verified_bot=verified_bot, trade=trade,
            rounded_size=rounded_size, pinned_environment=pinned_environment,
            pinned_account=pinned_account, pinned_dex=pinned_dex,
        )
        if result.state != "request_only" or result.submit_authorized:
            return OfflineMutationReview(
                action_class="new_entry", reason="new entry invalid; hold")
        return OfflineMutationReview(
            state="request_only", action_class="new_entry",
            reason="synthetic entry request only; no order dispatch",
            request_json=result.request_json,
        )

    if action in ("pyramid_long", "pyramid_short"):
        if verified_bot != "aggressive":
            return OfflineMutationReview(
                action_class="pyramid_increase",
                reason="pyramid action not part of this bot strategy")
        if (trade.get("side") != ("long" if action == "pyramid_long" else "short")
                or not _positive_decimal(rounded_size)):
            return OfflineMutationReview(
                action_class="pyramid_increase",
                reason="pyramid payload invalid; hold")
        return OfflineMutationReview(
            action_class="pyramid_increase",
            reason="HOLD: existing-position ownership, account fence and "
                   "increased-size authorization not established")

    if action == "close":
        # The original code uses market_close(coin) when close_size is missing
        # or nonpositive; that UNSIZED fallback is categorically unsafe.
        # Even an explicitly positive size is not enough without separately
        # authenticated, fresh, reconciled bot-owned quantity.
        close_size = trade.get("close_size")
        if not _positive_decimal(close_size):
            return OfflineMutationReview(
                action_class="close",
                reason="HOLD: missing, nonpositive or untrusted close quantity")
        return OfflineMutationReview(
            action_class="close",
            reason="HOLD: bounded reduce-only ownership and current account "
                   "position not independently verified")

    if action == "update_leverage":
        return OfflineMutationReview(
            action_class="leverage_change",
            reason="HOLD: independent single-writer account-scoped "
                   "leverage mutation not implemented")

    return OfflineMutationReview(
        reason="unknown action; fail-closed offline review")
