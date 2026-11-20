"""Conservative account-wide synthetic re-entry lock gate. ALWAYS HOLD.

This pure helper models a proposed future lock decision at the boundary
between signer-free strategy proposals and the protected sole writer.
It is NOT persistent: caller-provided statuses, signal snapshots, time,
bot identity and account scope are NOT trusted. No I/O, credentials,
clocks, exchange SDK, wallet, remote transport, release, resend or signer.

IMPORTANT divergence from reentry_lock.py (legacy source): that code can
remove a pending lock if a position is still observed open, or release
on signal reset / 15-minute Aggressive cooldown. The protected sender
must never interpret an observation, reset, or elapsed time as proof
an unknown-ACK exit was reconciled. Even a "confirmed_closed" caller
claim yields only a human REVIEW CANDIDATE; locks stay in force until
independently authenticated fill/position evidence and a durable,
serialized authorization path are reviewed and implemented.
"""
from dataclasses import dataclass
import re

from sender_review.pure_strategy_decisions_offline import TICKER_TO_COIN

_COINS = frozenset(TICKER_TO_COIN.values())
_BOTS = frozenset(("daily", "intraday", "aggressive"))
_NONCE = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_STATES = frozenset(("pending_exit", "unknown_ack", "partial_fill",
                     "confirmed_closed_fixture"))
_MUTATIONS = frozenset(("open_long", "open_short", "pyramid_long",
                        "pyramid_short", "close", "request_leverage"))
_LONG = frozenset(("buy", "hold_long"))
_SHORT = frozenset(("enter_short", "hold_short"))
_SIGNALS = _LONG | _SHORT | frozenset((
    "sell_exit", "cover_short", "liquidate", "hold", "idle",
))


@dataclass(frozen=True)
class SyntheticReentryLock:
    bot: str
    coin: str
    side: str
    nonce: str
    fence: int
    state: str
    created_epoch: int


@dataclass(frozen=True)
class OfflineReentryLockReview:
    state: str = "HOLD"
    reason: str = "no independently authenticated durable lock state"
    fixture_valid: bool = False
    held_coins: tuple[str, ...] = ()
    blocked_actions: tuple[dict, ...] = ()
    unaffected_review_proposals: tuple[dict, ...] = ()
    candidate_release_reviews: tuple[tuple[str, str], ...] = ()
    operator_reconciliation_required: bool = False
    account_wide_identity_verified: bool = False
    exchange_exit_confirmed: bool = False
    durable_lock_persisted: bool = False
    lock_released: bool = False
    retry_authorized: bool = False
    close_authorized: bool = False
    submit_authorized: bool = False
    signing_enabled: bool = False


def inspect_reentry_lock_transition_offline(
    *, requesting_bot, locks, proposals, signal_by_coin,
    synthetic_now_epoch, aggressive_cooldown_seconds=900,
):
    """Filter untrusted proposed mutations on locked coins; NEVER GO.

    No local or remote state is altered. The output is an offline diagnostic
    that cannot confer exchange, lock-release, close or order authority.
    """
    denied = OfflineReentryLockReview()
    if (type(requesting_bot) is not str or requesting_bot not in _BOTS
            or type(locks) is not tuple or len(locks) > 256
            or type(proposals) not in (tuple, list) or len(proposals) > 256
            or type(signal_by_coin) is not dict
            or len(signal_by_coin) > len(_COINS)
            or type(synthetic_now_epoch) is not int
            or not 0 <= synthetic_now_epoch <= 9007199254740991
            or type(aggressive_cooldown_seconds) is not int
            or not 900 <= aggressive_cooldown_seconds <= 86400):
        return denied
    by_coin = {}
    for lock in locks:
        if (type(lock) is not SyntheticReentryLock
                or type(lock.bot) is not str or lock.bot not in _BOTS
                or type(lock.coin) is not str or lock.coin not in _COINS
                or lock.coin in by_coin
                or type(lock.side) is not str or lock.side not in ("long", "short")
                or type(lock.nonce) is not str
                or _NONCE.fullmatch(lock.nonce) is None
                or type(lock.fence) is not int or lock.fence <= 0
                or type(lock.state) is not str or lock.state not in _STATES
                or type(lock.created_epoch) is not int
                or not 0 <= lock.created_epoch <= synthetic_now_epoch):
            return OfflineReentryLockReview(
                reason="invalid or conflicting account-wide lock fixture")
        by_coin[lock.coin] = lock
    for coin, signal in signal_by_coin.items():
        if (type(coin) is not str or coin not in _COINS
                or type(signal) is not str or signal not in _SIGNALS):
            return OfflineReentryLockReview(reason="unverified signal fixture")
    for action in proposals:
        if (type(action) is not dict
                or type(action.get("hl_coin")) is not str
                or action["hl_coin"] not in _COINS
                or type(action.get("action")) is not str
                or action["action"] not in _MUTATIONS):
            return OfflineReentryLockReview(
                reason="invalid proposed mutation fixture")
    blocked = tuple(dict(a) for a in proposals if a["hl_coin"] in by_coin)
    unaffected = tuple(dict(a) for a in proposals if a["hl_coin"] not in by_coin)
    candidates = []
    for coin, lock in by_coin.items():
        if lock.state != "confirmed_closed_fixture":
            # No reset or cooldown can clear uncertain / partially filled
            # order outcomes. The same restriction applies across bots.
            continue
        signal = signal_by_coin.get(coin)
        if signal is None:
            continue
        still_same = (signal in (_LONG if lock.side == "long" else _SHORT))
        elapsed = synthetic_now_epoch - lock.created_epoch
        cooldown_candidate = (lock.bot == "aggressive"
                              and elapsed >= aggressive_cooldown_seconds)
        if not still_same or cooldown_candidate:
            candidates.append((coin, "signal_reset_review" if not still_same
                               else "cooldown_review"))
    return OfflineReentryLockReview(
        reason="synthetic lock filtering only; no account-wide durable "
               "reconciliation or authority to release or execute",
        fixture_valid=True,
        held_coins=tuple(by_coin),
        blocked_actions=blocked,
        unaffected_review_proposals=unaffected,
        candidate_release_reviews=tuple(candidates),
        operator_reconciliation_required=bool(blocked or by_coin),
    )
