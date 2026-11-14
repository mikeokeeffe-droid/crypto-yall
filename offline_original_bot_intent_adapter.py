"""Review-only translation of original bot trade decisions into CI entry intents.

This module does NOT load executors, access Hyperliquid, authenticate a bot,
write a database, reserve an order, or authorize submission. The calling
coordinator must independently verify the workload identity and pinned
account/environment before trusting the resulting fields.

Pyramid adds and closes are intentionally unsupported until their separate
ownership/quantity policies are reviewed. Original strategies are untouched.
"""
from dataclasses import dataclass
import json
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


@dataclass(frozen=True)
class OfflineSignerFreeEntryHandoff:
    """A *request* to an independent coordinator; never an order permit."""
    state: str = "hold"
    request_json: str | None = None
    reason: str = "not approved"
    submit_authorized: bool = False


@dataclass(frozen=True)
class OfflineEntryAckReview:
    state: str = "hold"
    reason: str = "no trusted coordinator acknowledgement"
    submit_authorized: bool = False


def prepare_signer_free_entry_handoff_offline(
    *, verified_bot, trade, rounded_size, pinned_environment,
    pinned_account, pinned_dex=""
):
    """Compose the existing CI Unix-socket entry protocol without a signer.

    Reuse the original intent projection and forward only decision fields.
    Bot identity, account, DEX, environment, keys and DB roles MUST NOT be
    client-supplied on the wire; the CI server authenticates the peer and
    independently pins the scope. The 'verified' parameters are only test
    harness inputs here and are not actual workload authentication.

    Pyramids, closes and leverage mutations deliberately HOLD, not silently
    converted into a new entry. No SDK, socket, network or DB access occurs.
    """
    projected = project_original_entry(
        verified_bot=verified_bot, trade=trade,
        rounded_size=rounded_size,
        pinned_environment=pinned_environment,
        pinned_account=pinned_account, pinned_dex=pinned_dex,
    )
    if projected is None or projected.submit_authorized:
        return OfflineSignerFreeEntryHandoff(
            reason="unapproved action, account scope or exact rounded size"
        )
    side = "long" if projected.action == "open_long" else "short"
    payload = {
        "operation": "request_entry",
        "action": projected.action,
        "side": side,
        "hl_coin": projected.coin,
        "rounded_size": projected.size,
    }
    wire = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if len(wire.encode("utf-8")) > 1024:
        return OfflineSignerFreeEntryHandoff(reason="oversized offline entry request")
    return OfflineSignerFreeEntryHandoff(
        state="request_only",
        request_json=wire,
        reason="send only to separately authenticated disposable CI coordinator; "
               "no direct exchange submission or ownership",
    )


def review_signer_free_entry_ack_offline(*, reply_bytes):
    """Classify an untrusted CI-only coordinator reply without granting orders.

    An attacker-controlled or changed reply cannot turn the bot back into
    an exchange sender. Even a successful offline reservation is NOT a trade.
    """
    def hold(why):
        return OfflineEntryAckReview(reason=why)

    if type(reply_bytes) is not bytes or not 0 < len(reply_bytes) <= 1024:
        return hold("invalid coordinator reply")
    def no_duplicate_keys(pairs):
        parsed = {}
        for key, value in pairs:
            if key in parsed:
                raise ValueError("duplicate coordinator response field")
            parsed[key] = value
        return parsed
    try:
        response = json.loads(
            reply_bytes.decode("utf-8"), object_pairs_hook=no_duplicate_keys,
        )
    except (UnicodeError, ValueError):
        return hold("malformed or duplicate coordinator response")
    if (type(response) is not dict
            or set(response) != {"state", "submit_authorized"}
            or response["submit_authorized"] is not False):
        return hold("coordinator response is not a non-authorizing reply")
    if response["state"] == "reserved_offline_only":
        return OfflineEntryAckReview(
            state="recorded_offline_only",
            reason="CI reservation recorded; direct exchange submission forbidden",
        )
    if response["state"] == "hold":
        return hold("coordinator held the request")
    return hold("unknown offline coordinator response state")
