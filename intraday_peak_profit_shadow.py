"""Read-only Intraday peak-profit shadow research.

No private key or Exchange client is used. This module observes Intraday-owned
positions and records hypothetical exits only; it cannot place orders.

It keeps the original fixed fallback comparisons and adds an adaptive tier:
  EARLY       peak >= +0.50% and < +3.00%: break-even floor (0.00%)
  ESTABLISHED peak >= +3.00% and < +5.00%: trail peak by 1.50pp
  STRONG      peak >= +5.00%: trail peak by 2.00pp

The strong tier is deliberately looser. ATR/Chandelier remain separate shadow
signals in intraday_shadow_report.py; this study records the tiered percentage
trail beside them without changing live execution.
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

ADAPTIVE_EARLY_ARM_PCT = 0.50
ADAPTIVE_ESTABLISHED_PCT = 3.00
ADAPTIVE_STRONG_PCT = 5.00
ADAPTIVE_ESTABLISHED_GIVEBACK_PP = 1.50
ADAPTIVE_STRONG_GIVEBACK_PP = 2.00

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
    levels = {
        f"fallback_{int(fallback)}pp": max(0.0, peak_pct - fallback)
        for fallback in PERCENTAGE_POINT_FALLBACKS
    }
    levels["retain_50pct"] = max(0.0, peak_pct * RETENTION_FRACTION)
    return levels


def adaptive_level(peak_pct: float) -> tuple[str, bool, float | None]:
    """Return (tier, armed, hypothetical exit return %)."""
    if peak_pct < ADAPTIVE_EARLY_ARM_PCT:
        return "UNARMED", False, None
    if peak_pct < ADAPTIVE_ESTABLISHED_PCT:
        return "EARLY", True, 0.0
    if peak_pct < ADAPTIVE_STRONG_PCT:
        return (
            "ESTABLISHED",
            True,
            max(0.0, peak_pct - ADAPTIVE_ESTABLISHED_GIVEBACK_PP),
        )
    return (
        "STRONG",
        True,
        max(0.0, peak_pct - ADAPTIVE_STRONG_GIVEBACK_PP),
    )


def new_trigger_state() -> dict:
    return {
        "armed": False,
        "triggered": False,
        "triggered_at": None,
        "trigger_level_pct": None,
        "observed_return_pct": None,
        "peak_at_trigger_pct": None,
        "approx_trigger_pnl": None,
    }


def new_rule_state() -> dict[str, dict]:
    names = [
        *(f"fallback_{int(fallback)}pp" for fallback in PERCENTAGE_POINT_FALLBACKS),
        "retain_50pct",
    ]
    return {name: new_trigger_state() for name in names}


def ensure_rule_state(episode: dict) -> dict[str, dict]:
    rules = episode.get("rules")
    if not isinstance(rules, dict):
        rules = new_rule_state()
        episode["rules"] = rules
    for name, default in new_rule_state().items():
        if not isinstance(rules.get(name), dict):
            rules[name] = default
        else:
            for key, value in default.items():
                rules[name].setdefault(key, value)
    return rules


def ensure_adaptive_state(episode: dict) -> dict:
    adaptive = episode.get("adaptive_tier")
    if not isinstance(adaptive, dict):
        adaptive = new_trigger_state()
        adaptive.update({"tier": "UNARMED", "highest_tier": "UNARMED"})
        episode["adaptive_tier"] = adaptive
    return adaptive


def finalize_episode(state: dict, episode: dict, now: dt.datetime, reason: str) -> dict:
    outcome = {**episode, "ended_at": now.isoformat(), "end_reason": reason}
    close = latest_filled_close(
        state, str(episode.get("coin")), episode.get("started_at")
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
    state: dict, managed_positions: dict, now: dt.datetime
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

    for coin in list(active):
        if coin not in managed_positions:
            completed.append(
                finalize_episode(
                    state, active.pop(coin), now, "position_no_longer_owned"
                )
            )

    for coin, position in sorted(managed_positions.items()):
        side = "long" if float(position["size"]) > 0 else "short"
        entry_px = float(position["entry_px"])
        notional = entry_notional(position)
        current_pct = return_pct(position)
        current_pnl = float(position["unrealized_pnl"])
        episode = active.get(coin)

        if episode is not None and (
            episode.get("side") != side
            or abs(float(episode.get("entry_px", entry_px)) - entry_px) > 1e-12
        ):
            completed.append(finalize_episode(state, episode, now, "position_changed"))
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
                "adaptive_tier": {
                    **new_trigger_state(),
                    "tier": "UNARMED",
                    "highest_tier": "UNARMED",
                },
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
            if rule.get("armed") and not rule.get("triggered") and current_pct <= level:
                rule.update({
                    "triggered": True,
                    "triggered_at": now.isoformat(),
                    "trigger_level_pct": level,
                    "observed_return_pct": current_pct,
                    "peak_at_trigger_pct": peak_pct,
                    "approx_trigger_pnl": notional * level / 100.0,
                })

        tier, adaptive_armed, adaptive_exit = adaptive_level(peak_pct)
        adaptive = ensure_adaptive_state(episode)
        adaptive["tier"] = tier
        tier_rank = {"UNARMED": 0, "EARLY": 1, "ESTABLISHED": 2, "STRONG": 3}
        if tier_rank[tier] > tier_rank.get(str(adaptive.get("highest_tier")), 0):
            adaptive["highest_tier"] = tier
            adaptive["tier_changed_at"] = now.isoformat()
        if adaptive_armed:
            adaptive["armed"] = True
        adaptive["current_exit_level_pct"] = adaptive_exit
        if (
            adaptive_armed
            and adaptive_exit is not None
            and not adaptive.get("triggered")
            and current_pct <= adaptive_exit
        ):
            adaptive.update({
                "triggered": True,
                "triggered_at": now.isoformat(),
                "trigger_level_pct": adaptive_exit,
                "observed_return_pct": current_pct,
                "peak_at_trigger_pct": peak_pct,
                "approx_trigger_pnl": notional * adaptive_exit / 100.0,
                "tier_at_trigger": tier,
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
                "adaptive_tier": tier,
                "adaptive_armed": adaptive_armed,
                "adaptive_exit_level_pct": adaptive_exit,
                "adaptive_triggered": bool(adaptive.get("triggered")),
                "levels": levels,
                "comparison_note": (
                    "Shadow only. Return is unrealized P&L / entry notional, not "
                    "leveraged ROE. Hypothetical exits exclude closing fee, funding "
                    "and slippage."
                ),
            })

        if adaptive.get("triggered"):
            adaptive_status = (
                f"{tier}=TRIGGERED@{float(adaptive.get('trigger_level_pct', 0.0)):.2f}%"
            )
        elif adaptive_armed and adaptive_exit is not None:
            adaptive_status = f"{tier}=HOLD>{adaptive_exit:.2f}%"
        else:
            adaptive_status = "UNARMED"

        summary_lines.append(
            f"PeakProfit {coin} {side.upper()} | current={current_pct:+.3f}% "
            f"peak={peak_pct:+.3f}% | adaptive={adaptive_status}"
        )

    state["shadow_peak_profit_active"] = active
    state["shadow_peak_profit_history"] = history[-MAX_HISTORY:]
    state["shadow_peak_profit_completed"] = completed[-MAX_COMPLETED:]
    state["last_peak_profit_shadow_snapshot"] = {
        "timestamp": now.isoformat(),
        "adaptive_config": {
            "early_arm_pct": ADAPTIVE_EARLY_ARM_PCT,
            "established_pct": ADAPTIVE_ESTABLISHED_PCT,
            "strong_pct": ADAPTIVE_STRONG_PCT,
            "established_giveback_pp": ADAPTIVE_ESTABLISHED_GIVEBACK_PP,
            "strong_giveback_pp": ADAPTIVE_STRONG_GIVEBACK_PP,
            "live_orders": False,
        },
        "positions": [
            {
                "coin": coin,
                "side": active[coin].get("side"),
                "current_return_pct": active[coin].get("last_return_pct"),
                "peak_return_pct": active[coin].get("peak_return_pct"),
                "adaptive_tier": active[coin].get("adaptive_tier"),
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
        coin: pos for coin, pos in exchange_positions.items() if coin in owned_coins
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
