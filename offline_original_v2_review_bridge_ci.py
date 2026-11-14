"""Offline-only V2 draft -> disposable PostgreSQL *review* journal bridge.

This is a test-harness-side adapter, NOT a bot runtime DB client, signer,
order sender, approved risk policy or deployment plan. The server-side CI
harness independently supplies bot/account/environment pins and an isolated
restricted database factory; none come from the untrusted V2 draft.

V2 has no close/dispatch/mark/release endpoint. No exchange SDK, network
client, trading key, original executor import, or live service may be used.
A positive record merely means an immutable review row was committed.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import os
import re
import uuid

from offline_leverage_bound_entry_draft_ci import OfflineLeverageDraft

_BOTS = frozenset(("daily", "intraday", "aggressive"))
_FIELDS = frozenset((
    "operation", "action", "side", "hl_coin", "rounded_size",
    "requested_leverage", "cross_margin_requested",
))
_COIN = re.compile(r"[A-Z0-9]+\Z", re.ASCII)
_ACCOUNT = re.compile(r"0x[0-9a-f]{40}\Z", re.ASCII)
_SIZE = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z", re.ASCII)


@dataclass(frozen=True)
class OfflineV2ReviewAdmission:
    state: str = "hold"
    token: uuid.UUID | None = None
    fence: int | None = None
    submit_authorized: bool = False
    leverage_applied: bool = False


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate V2 review field")
        result[key] = value
    return result


def record_v2_draft_for_offline_review(
    *, connection_factory, verified_bot, pinned_environment, pinned_account,
    draft, request_id, pinned_dex="",
):
    """HOLD on invalid, mismatched or ambiguously committed CI review data.

    The bridge never trusts a client assertion of auth, fill, leverage applied
    or sending permission. Database session_user separately enforces bot/scope.
    The bridge never exposes a method to dispatch, close or release a claim.
    """
    held = OfflineV2ReviewAdmission()
    if (os.environ.get("ISOLATED_POSTGRES_CI") != "1"
            or os.environ.get("PGDATABASE") != "safety_test"
            or os.environ.get("PGHOST") not in ("localhost", "127.0.0.1")
            or type(verified_bot) is not str or verified_bot not in _BOTS
            or type(pinned_environment) is not str
            or pinned_environment not in ("mainnet", "testnet")
            or type(pinned_account) is not str
            or _ACCOUNT.fullmatch(pinned_account) is None
            or pinned_dex != ""
            or type(request_id) is not uuid.UUID
            or type(draft) is not OfflineLeverageDraft
            or draft.state != "review_only"
            or draft.submit_authorized is not False
            or draft.leverage_applied is not False
            or type(draft.review_json) is not str
            or not 0 < len(draft.review_json.encode("utf-8")) <= 1024
            or not callable(connection_factory)):
        return held

    try:
        data = json.loads(draft.review_json, object_pairs_hook=_unique_pairs)
        if type(data) is not dict or set(data) != _FIELDS:
            return held
        action = data["action"]
        coin = data["hl_coin"]
        size = data["rounded_size"]
        leverage = data["requested_leverage"]
        if (data["operation"] != "review_entry_leverage_v2"
                or action not in ("open_long", "open_short")
                or data["side"] != ("long" if action == "open_long" else "short")
                or type(coin) is not str or _COIN.fullmatch(coin) is None
                or type(size) is not str or _SIZE.fullmatch(size) is None
                or type(leverage) is not int or not 1 <= leverage <= 5
                or data["cross_margin_requested"] is not True):
            return held
        quantity = Decimal(size)
        if not quantity.is_finite() or quantity <= 0:
            return held
    except (UnicodeError, ValueError, TypeError, InvalidOperation):
        return held

    try:
        with connection_factory() as conn:
            if conn.info.host not in ("localhost", "127.0.0.1", "::1"):
                return held
            identity = conn.execute(
                "select current_database(),session_user,current_user"
            ).fetchone()
            if identity != (
                "safety_test", "entry_login_" + verified_bot,
                "entry_login_" + verified_bot,
            ):
                return held
            row = conn.execute(
                "select recorded,review_token,fencing "
                "from public.ci_sender_v2_record_review("
                "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (pinned_environment, pinned_account, pinned_dex, coin,
                 verified_bot, action, quantity, leverage,
                 "cross", request_id),
            ).fetchone()
            if (row is None or row[0] is not True
                    or type(row[1]) is not uuid.UUID
                    or type(row[2]) is not int or row[2] <= 0):
                return held
            token, fence = row[1:3]
        # Return only after commit, and NEVER return order authority.
        return OfflineV2ReviewAdmission("recorded_review_only", token, fence)
    except Exception:
        # Database failure, commit uncertainty or timeout = HOLD.
        # Never auto-retry with another request ID.
        return held
