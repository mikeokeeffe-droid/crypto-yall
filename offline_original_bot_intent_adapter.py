"""Review-only translation of original bot trade decisions into CI entry intents.

This module does NOT load executors, access Hyperliquid, authenticate a bot,
write a database, reserve an order, or authorize submission. The calling
coordinator must independently verify the workload identity and pinned
account/environment before trusting the resulting fields.

Pyramid adds and closes are intentionally unsupported until their separate
ownership/quantity policies are reviewed. Original strategies are untouched.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

_BOTS = frozenset(("daily", "intraday", "aggressive"))
_SCOPES = frozenset(("mainnet", "testnet"))
_COIN = re.compile(r"[A-Z0-9]+\Z", re.ASCII)
_ACCOUNT = re.compile(r"0x[0-9a-f]{40}\Z", re.ASCII)
_QUANTITY = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z", re.ASCII)


@dataclass(frozen=True)
class OfflineOriginalEntryIntent:
    bot: str
    action: str
    coin: str
    size: str
    environment: str
    account: str
    dex: str = ""
    submit_authorized: bool = False


def project_original_entry(*, verified_bot, trade, rounded_size,
                           pinned_environment, pinned_account, pinned_dex=""):
    """Return a strict *synthetic* new-entry intent, or None (HOLD).

    verified_bot and pinned_* are provided by a separate trusted test harness,
    never derived from trade['bot'] or the signer address. Quantity is a
    decimal string representing size *after* the bot's rounding logic.
    This shape can be passed to disposable ci_record_pre_submit_intent only.
    """
    if (type(verified_bot) is not str or verified_bot not in _BOTS
        or type(trade) is not dict
        or type(pinned_environment) is not str
        or pinned_environment not in _SCOPES
        or type(pinned_account) is not str
        or _ACCOUNT.fullmatch(pinned_account) is None
        or pinned_dex != ""
        or type(rounded_size) is not str
        or _QUANTITY.fullmatch(rounded_size) is None):
        return None

    action = trade.get("action")
    coin = trade.get("hl_coin")
    side = trade.get("side")
    if (action not in ("open_long", "open_short")
        or side != ("long" if action == "open_long" else "short")
        or type(coin) is not str
        or _COIN.fullmatch(coin) is None
        or "bot" in trade or "account" in trade
        or "environment" in trade or "dex" in trade):
        return None
    try:
        value = Decimal(rounded_size)
    except InvalidOperation:
        return None
    if not value.is_finite() or value <= 0:
        return None
    return OfflineOriginalEntryIntent(
        verified_bot, action, coin, rounded_size,
        pinned_environment, pinned_account,
    )
