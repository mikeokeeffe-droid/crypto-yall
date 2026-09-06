"""Live profit protection wrapper for the Intraday executor.

Keeps Intraday entry logic unchanged and gives existing signal exits precedence.

Two live protection layers are applied on entry-notional return:
1) Small-profit floor: once peak return reaches +1.00%, close if the current
   return falls to +0.25% or lower.
2) Existing trailing protection: once peak reaches +0.50%, close after a
   2.00 percentage-point giveback from the tracked peak.

After any protection exit, same-setup re-entry is blocked until the strategy
signal resets or flips.
"""

from __future__ import annotations
import os
import intraday_executor as base
from reentry_lock import block_locked_entries, mark_pending_lock, refresh_locks

ARM_PCT = float(os.environ.get("INTRADAY_PROFIT_ARM_PCT", "0.5"))
GIVEBACK_PCT = float(os.environ.get("INTRADAY_PROFIT_GIVEBACK_PCT", "2.0"))
SMALL_PROFIT_PEAK_PCT = float(os.environ.get("INTRADAY_SMALL_PROFIT_PEAK_PCT", "1.0"))
SMALL_PROFIT_FLOOR_PCT = float(os.environ.get("INTRADAY_SMALL_PROFIT_FLOOR_PCT", "0.25"))
ENABLED = os.environ.get("INTRADAY_PROFIT_PROTECTION", "ON").upper() != "OFF"
_original_decide_trades = base.decide_trades
_original_send_telegram = base._send_telegram
_state: dict | None = None


def _protected_decide_trades(signals: dict, open_positions: dict, max_positions: int) -> list[dict]:
    trades = _original_decide_trades(signals, open_positions, max_positions)
    if not ENABLED or _state is None:
        return trades

    locks = refresh_locks(_state, signals, base.HL_SYMBOL_MAP, open_positions)
    trades = block_locked_entries(trades, locks)
    signal_closes = {t["hl_coin"] for t in trades if t.get("action") == "close"}
    peak_returns = _state.get("peak_return_pct", {}) or {}
    ticker_by_coin = {coin: ticker for ticker, coin in base.HL_SYMBOL_MAP.items()}
    protection_closes: dict[str, dict] = {}

    for coin, pos in open_positions.items():
        if coin in signal_closes:
            continue

        entry_px = float(pos.get("entry_px", 0.0) or 0.0)
        size = abs(float(pos.get("size", 0.0) or 0.0))
        current_pnl = float(pos.get("unrealized_pnl", 0.0) or 0.0)
        if entry_px <= 0 or size <= 0:
            continue

        current_pct = current_pnl / (entry_px * size) * 100.0
        peak_pct = max(float(peak_returns.get(coin, 0.0) or 0.0), current_pct)
        giveback = peak_pct - current_pct

        small_profit_trigger = (
            peak_pct >= SMALL_PROFIT_PEAK_PCT
            and current_pct <= SMALL_PROFIT_FLOOR_PCT
        )
        trailing_trigger = (
            peak_pct >= ARM_PCT
            and giveback >= GIVEBACK_PCT
        )

        if not small_profit_trigger and not trailing_trigger:
            continue

        ticker = ticker_by_coin.get(coin)
        if not ticker:
            print(f"Intraday profit protection skipped {coin}: ticker unavailable")
            continue

        side = "long" if float(pos.get("size", 0.0)) > 0 else "short"
        if small_profit_trigger:
            protection_mode = "SMALL PROFIT FLOOR"
            reason = (
                f"small-profit protection: peak {peak_pct:+.2f}% -> current {current_pct:+.2f}% "
                f"(floor +{SMALL_PROFIT_FLOOR_PCT:.2f}% after peak +{SMALL_PROFIT_PEAK_PCT:.2f}%)"
            )
        else:
            protection_mode = "TRAILING PROFIT PROTECTION"
            reason = (
                f"profit protection: peak {peak_pct:+.2f}% -> current {current_pct:+.2f}% "
                f"({giveback:.2f}pp giveback; armed at {ARM_PCT:.2f}%)"
            )

        protection_closes[coin] = {
            "ticker": ticker, "hl_coin": coin, "action": "close", "side": side,
            "reason": reason,
            "exit_type": "PROFIT PROTECTION",
            "protection_mode": protection_mode,
            "protection_arm_pct": ARM_PCT,
            "protection_peak_pct": peak_pct,
            "protection_trigger_return_pct": current_pct,
            "protection_giveback_pct": giveback,
            "small_profit_peak_pct": SMALL_PROFIT_PEAK_PCT,
            "small_profit_floor_pct": SMALL_PROFIT_FLOOR_PCT,
        }
        mark_pending_lock(_state, coin, side)

    if not protection_closes:
        return trades

    trades = [t for t in trades if t.get("hl_coin") not in protection_closes]
    trades.extend(protection_closes.values())
    return trades


def _telegram_with_exit_diagnostics(results: list[dict], summary: str) -> None:
    enriched = []
    for item in results:
        r = dict(item)
        if r.get("action") == "close":
            reason = str(r.get("reason", ""))
            is_protection = reason.startswith("profit protection:") or reason.startswith("small-profit protection:")
            exit_type = "PROFIT PROTECTION" if is_protection else "SIGNAL EXIT"
            details = [f"Exit type: {exit_type}"]
            if r.get("peak_return_pct") is not None:
                details.append(f"Peak return: {float(r['peak_return_pct']):+.2f}%")
            if r.get("realized_return_pct") is not None:
                details.append(f"Net return: {float(r['realized_return_pct']):+.2f}%")
            if is_protection:
                if r.get("protection_mode"):
                    details.append(f"Protection mode: {r['protection_mode']}")
                details.append(
                    f"Small-profit floor: peak +{SMALL_PROFIT_PEAK_PCT:.2f}% / floor +{SMALL_PROFIT_FLOOR_PCT:.2f}%"
                )
                details.append(
                    f"Trailing rule: arm +{ARM_PCT:.2f}% / max {GIVEBACK_PCT:.2f}pp giveback"
                )
                details.append("Re-entry: locked until signal reset")
            r["reason"] = reason + " | " + " | ".join(details)
        enriched.append(r)
    _original_send_telegram(enriched, summary)


def main() -> None:
    global _state
    original_load_state = base.load_state

    def load_and_capture() -> dict:
        global _state
        state = original_load_state()
        _state = state
        return state

    base.load_state = load_and_capture
    base.decide_trades = _protected_decide_trades
    base._send_telegram = _telegram_with_exit_diagnostics
    print(
        f"Intraday profit protection {'ON' if ENABLED else 'OFF'}: "
        f"small-profit peak +{SMALL_PROFIT_PEAK_PCT:.2f}% -> floor +{SMALL_PROFIT_FLOOR_PCT:.2f}% | "
        f"trail arm +{ARM_PCT:.2f}% / max giveback {GIVEBACK_PCT:.2f}pp | re-entry lock ON"
    )
    base.main()


if __name__ == "__main__":
    main()
