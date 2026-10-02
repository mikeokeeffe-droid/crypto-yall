"""State helpers for blocking immediate re-entry after a profit-protection exit.

A lock is side-specific and remains active while the strategy is still in the
same long/short holding condition that produced the closed trade. The lock is
released when the signal resets or flips. Callers may optionally supply a
cooldown so a continuing trend can be re-entered without waiting indefinitely.
"""

from __future__ import annotations

import datetime as dt

LOCK_KEY = "profit_reentry_locks"
LONG_ACTIONS = {"buy", "hold_long"}
SHORT_ACTIONS = {"enter_short", "hold_short"}


def _signal_action_for_coin(signals: dict, symbol_map: dict, coin: str) -> str | None:
    for ticker, mapped_coin in symbol_map.items():
        if mapped_coin != coin:
            continue
        info = signals.get(ticker)
        if isinstance(info, dict):
            action = info.get("action")
            return str(action) if action is not None else None
    return None


def refresh_locks(
    state: dict,
    signals: dict,
    symbol_map: dict,
    open_positions: dict,
    cooldown_minutes: int | None = None,
) -> dict:
    raw = state.get(LOCK_KEY, {}) or {}
    locks = {str(coin): dict(value) for coin, value in raw.items() if isinstance(value, dict)}

    for coin in list(locks):
        lock = locks[coin]
        side = str(lock.get("side", "")).lower()
        pending = bool(lock.get("pending", False))

        if pending:
            if coin in open_positions:
                locks.pop(coin, None)
                continue
            lock["pending"] = False
            lock["confirmed_at"] = dt.datetime.now(dt.UTC).isoformat()

        created_at_raw = lock.get("confirmed_at") or lock.get("created_at")
        if cooldown_minutes is not None and created_at_raw:
            try:
                created_at = dt.datetime.fromisoformat(str(created_at_raw).replace("Z", "+00:00"))
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=dt.UTC)
                elapsed = dt.datetime.now(dt.UTC) - created_at
                if elapsed >= dt.timedelta(minutes=cooldown_minutes):
                    print(
                        f"Profit re-entry lock released for {coin}: "
                        f"{cooldown_minutes}-minute cooldown elapsed"
                    )
                    locks.pop(coin, None)
                    continue
            except (TypeError, ValueError):
                pass

        action = _signal_action_for_coin(signals, symbol_map, coin)
        if action is None:
            continue

        same_setup = (
            (side == "long" and action in LONG_ACTIONS)
            or (side == "short" and action in SHORT_ACTIONS)
        )
        if not same_setup:
            print(f"Profit re-entry lock released for {coin}: {side} setup reset to {action}")
            locks.pop(coin, None)

    state[LOCK_KEY] = locks
    return locks


def block_locked_entries(
    trades: list[dict],
    locks: dict,
    cooldown_minutes: int | None = None,
) -> list[dict]:
    filtered = []
    for trade in trades:
        action = str(trade.get("action", ""))
        coin = str(trade.get("hl_coin", ""))
        if action in {"open_long", "open_short"} and coin in locks:
            wait_for = (
                f"signal reset or {cooldown_minutes}-minute cooldown"
                if cooldown_minutes is not None
                else "a fresh signal reset"
            )
            print(f"Profit re-entry lock blocked {action} for {coin}; waiting for {wait_for}")
            continue
        filtered.append(trade)
    return filtered


def mark_pending_lock(state: dict, coin: str, side: str) -> None:
    locks = state.setdefault(LOCK_KEY, {})
    locks[str(coin)] = {
        "side": str(side).lower(),
        "pending": True,
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "reason": "profit protection",
    }
