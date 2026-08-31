"""
intraday_peak_profit_shadow.py — read-only peak-profit protection research.

This script never creates an Exchange client and never receives HL_PRIVATE_KEY.
It reads the Intraday-owned Hyperliquid positions, tracks the best unrealized
return reached by each position, and compares four hypothetical profit exits:

  1) give back 1.0 percentage point from peak
  2) give back 2.0 percentage points from peak
  3) give back 3.0 percentage points from peak
  4) retain 50% of the peak return

All rules arm after the position has reached +1.0% return on entry notional.
Once armed, the hypothetical exit level is floored at 0.0% so the research is
focused on protecting a winner rather than intentionally allowing it to become
a loser. The actual Intraday strategy remains unchanged.

Return percentage here is unrealized P&L divided by entry notional. It is not
Hyperliquid leveraged ROE. Shadow results are stored in the existing Intraday
Gist for later comparison with the actual live close.
"""

from __future__ import annotations

import datetime as dt

from intraday_shadow_report import (
    get_info_and_address,
    get_open_positions,
    latest_filled_close,
    load_state,
    save_state,
)


ARM_RETURN_PCT = 1.0
PERCENTAGE_POINT_FALLBACKS = (1.0, 2.0, 3.0)
RETENTION_FRACTION = 0.50
MAX_HISTORY = 1500
MAX_COMPLETED = 300


def entry_notional(position: dict) -> float:
    return abs(float(position["size"])) * float(position["entry_px"])


def return_pct(position: dict) -> float:
    notional = entry_notional(position)
    if notional <= 0:
        return 0.0
    return float(position["unrealized_pnl"]) / notional * 100.0


def rule_levels(peak_pct: float) -> dict[str, float]:
    """Return hypothetical exit levels in percentage points of entry notional."""
    levels = {
        f"fallback_{int(fallback)}pp": max(0.0, peak_pct - fallback)
        for fallback in PERCENTAGE_POINT_FALLBACKS
    }
    levels["retain_50pct"] = max(0.0, peak_pct * RETENTION_FRACTION)
    return levels


def new_rule_state() -> dict[str, dict]:
    names = [
        *(f"fallback_{int(fallback)}pp" for fallback in PERCENTAGE_POINT_FALLBACKS),
        "retain_50pct",
    ]
    return {
        name: {
            "armed": False,
            "triggered": False,
            "triggered_at": None,
            "trigger_level_pct": None,
            "observed_return_pct": None,
            "peak_at_trigger_pct": None,
            "approx_trigger_pnl": None,
        }
        for name in names
    }


def ensure_rule_state(episode: dict) -> dict[str, dict]:
    rules = episode.get("rules")
    if not isinstance(rules, dict):
        rules = new_rule_state()
        episode["rules"] = rules
        return rules

    for name, default in new_rule_state().items():
        if not isinstance(rules.get(name), dict):
            rules[name] = default
        else:
            for key, value in default.items():
                rules[name].setdefault(key, value)
    return rules


def finalize_episode(
    state: dict,
    episode: dict,
    now: dt.datetime,
    reason: str,
) -> dict:
    outcome = {
        **episode,
        "ended_at": now.isoformat(),
        "end_reason": reason,
    }

    close = latest_filled_close(
        state,
        str(episode.get("coin")),
        episode.get("started_at"),
    )
    if close is not None:
        outcome.update({
            "live_close_timestamp": close.get("timestamp"),
            "live_close_price": close.get("fill_price"),
            "live_realized_pnl": close.get("realized_pnl"),
            "live_gross_pnl": close.get("gross_closed_pnl"),
            "live_trading_fees": close.get("trading_fees"),
            "live_funding_pnl": close.get("funding_pnl"),
            "live_close_reason": close.get("reason"),
        })
    return outcome


def update_peak_profit_research(
    state: dict,
    managed_positions: dict,
    now: dt.datetime,
) -> list[str]:
    active = {
        str(k): dict(v)
        for k, v in (state.get("shadow_peak_profit_active", {}) or {}).items()
        if isinstance(v, dict)
    }
    history = list(state.get("shadow_peak_profit_history", []) or [])
    completed = list(state.get("shadow_peak_profit_completed", []) or [])
    hour_key = now.strftime("%Y-%m-%dT%H:00Z")
    summary_lines: list[str] = []

    # Finalize positions that have disappeared since the previous observation.
    for coin in list(active):
        if coin in managed_positions:
            continue
        completed.append(
            finalize_episode(
                state,
                active.pop(coin),
                now,
                "position_no_longer_owned",
            )
        )

    for coin, position in sorted(managed_positions.items()):
        side = "long" if float(position["size"]) > 0 else "short"
        entry_px = float(position["entry_px"])
        notional = entry_notional(position)
        current_pct = return_pct(position)
        current_pnl = float(position["unrealized_pnl"])
        episode = active.get(coin)

        # Reset research state if this is a new/reversed/re-entered position.
        if episode is not None and (
            episode.get("side") != side
            or abs(float(episode.get("entry_px", entry_px)) - entry_px) > 1e-12
        ):
            completed.append(
                finalize_episode(state, episode, now, "position_changed")
            )
            active.pop(coin, None)
            episode = None

        if episode is None:
            episode = {
                "coin": coin,
                "side": side,
                "entry_px": entry_px,
                "entry_notional": notional,
                "started_at": now.isoformat(),
                "peak_return_pct": current_pct,
                "peak_unrealized_pnl": current_pnl,
                "last_counted_hour": None,
                "rules": new_rule_state(),
            }
            active[coin] = episode

        peak_pct = max(float(episode.get("peak_return_pct", current_pct)), current_pct)
        peak_pnl = max(float(episode.get("peak_unrealized_pnl", current_pnl)), current_pnl)
        episode["peak_return_pct"] = peak_pct
        episode["peak_unrealized_pnl"] = peak_pnl
        episode["last_seen_at"] = now.isoformat()
        episode["last_return_pct"] = current_pct
        episode["last_unrealized_pnl"] = current_pnl

        levels = rule_levels(peak_pct)
        rules = ensure_rule_state(episode)
        armed = peak_pct >= ARM_RETURN_PCT

        for name, level in levels.items():
            rule = rules[name]
            if armed:
                rule["armed"] = True

            if (
                rule.get("armed")
                and not rule.get("triggered")
                and current_pct <= level
            ):
                rule.update({
                    "triggered": True,
                    "triggered_at": now.isoformat(),
                    "trigger_level_pct": level,
                    "observed_return_pct": current_pct,
                    "peak_at_trigger_pct": peak_pct,
                    "approx_trigger_pnl": notional * level / 100.0,
                })

        if episode.get("last_counted_hour") != hour_key:
            episode["last_counted_hour"] = hour_key
            history.append({
                "timestamp": now.isoformat(),
                "coin": coin,
                "side": side,
                "entry_px": entry_px,
                "entry_notional": notional,
                "unrealized_pnl": current_pnl,
                "return_pct": current_pct,
                "peak_return_pct": peak_pct,
                "armed": armed,
                "levels": levels,
                "rule_status": {
                    name: {
                        "armed": bool(rules[name].get("armed")),
                        "triggered": bool(rules[name].get("triggered")),
                    }
                    for name in levels
                },
                "comparison_note": (
                    "Return is unrealized P&L / entry notional, not leveraged ROE. "
                    "Hypothetical trigger P&L excludes closing fee, funding and slippage."
                ),
            })

        statuses = []
        for name, level in levels.items():
            rule = rules[name]
            if rule.get("triggered"):
                status = "TRIGGERED"
            elif rule.get("armed"):
                status = f"HOLD>{level:.2f}%"
            else:
                status = "NOT_ARMED"
            statuses.append(f"{name}={status}")

        summary_lines.append(
            f"PeakProfit {coin} {side.upper()} | current={current_pct:+.3f}% "
            f"peak={peak_pct:+.3f}% | " + " | ".join(statuses)
        )

    state["shadow_peak_profit_active"] = active
    state["shadow_peak_profit_history"] = history[-MAX_HISTORY:]
    state["shadow_peak_profit_completed"] = completed[-MAX_COMPLETED:]
    state["last_peak_profit_shadow_snapshot"] = {
        "timestamp": now.isoformat(),
        "arm_return_pct": ARM_RETURN_PCT,
        "fallback_percentage_points": list(PERCENTAGE_POINT_FALLBACKS),
        "retention_fraction": RETENTION_FRACTION,
        "positions": [
            {
                "coin": coin,
                "side": active[coin].get("side"),
                "current_return_pct": active[coin].get("last_return_pct"),
                "peak_return_pct": active[coin].get("peak_return_pct"),
                "rules": active[coin].get("rules"),
            }
            for coin in sorted(active)
        ],
    }
    return summary_lines


def main() -> None:
    now = dt.datetime.now(dt.UTC)
    print(f"Intraday peak-profit shadow started at {now.isoformat()}")
    print("READ ONLY: no private key, no Exchange client, no order methods")

    state = load_state()
    info, address = get_info_and_address()
    exchange_positions = get_open_positions(info, address)
    owned_coins = set(state.get("owned_coins", []) or [])
    managed = {
        coin: pos
        for coin, pos in exchange_positions.items()
        if coin in owned_coins
    }

    lines = update_peak_profit_research(state, managed, now)
    save_state(state)

    if not managed:
        print("PeakProfit shadow: no owned Intraday positions")
    else:
        for line in lines:
            print(line)

    print("Intraday peak-profit shadow done")


if __name__ == "__main__":
    main()
