"""
daily_bot_report.py — reporting-only aggregation for Aggressive, Intraday and Daily.

Reads the three existing private Gist state files and writes compact JSON
snapshots into reports/. It never imports executor modules and has no trading
capability.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

import requests

BOTS = {
    "aggressive": ("AGGRESSIVE_GIST_ID", "aggressive_state.json"),
    "intraday": ("INTRADAY_GIST_ID", "intraday_state.json"),
    "daily": ("GIST_ID", "crypto_yall_state.json"),
}


MIDCAP_SHORT_SHADOW_TICKERS = [
    "SOL-USD",
    "AVAX-USD",
    "LINK-USD",
    "SUI20947-USD",
    "XRP-USD",
    "ONDO-USD",
]


def _load_previous_short_shadow() -> dict[str, Any]:
    path = Path("reports/latest.json")
    if not path.exists():
        return {}
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
        value = previous.get("short_opportunity_check", {})
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _shadow_return_pct(entry_price: float, current_price: float) -> float:
    if entry_price <= 0:
        return 0.0
    return (entry_price - current_price) / entry_price * 100.0


def _shadow_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(r.get("gross_return_pct", 0.0) or 0.0) for r in rows]
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]
    decided = len(wins) + len(losses)
    return {
        "closed_trades": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / decided * 100.0, 2) if decided else None,
        "average_win_pct": round(sum(wins) / len(wins), 4) if wins else None,
        "average_loss_pct": round(sum(losses) / len(losses), 4) if losses else None,
        "cumulative_gross_return_pct": round(sum(values), 4),
    }


def _update_short_opportunity_check(previous: dict[str, Any], now: dt.datetime) -> dict[str, Any]:
    """
    Observation-only shadow for mid-cap shorts that live trading currently blocks.

    Tracks only fresh short signals seen after this feature starts. It never
    sends orders, imports executor modules, or changes live bot state.
    Shadow returns are price-only gross percentages: fees and funding excluded.
    """
    from intraday_data_loader import fetch_all_intraday, HL_SYMBOL_MAP
    from aggressive_strategy import (
        generate_aggressive_signals,
        classify_aggressive_signal,
    )
    from intraday_strategy import (
        generate_intraday_signals,
        classify_intraday_signal,
    )

    result = previous if isinstance(previous, dict) else {}
    result.setdefault("tracking_started_at", now.isoformat())
    result["updated_at"] = now.isoformat()
    result["scope"] = (
        "Shadow-only fresh short signals for SOL/AVAX/LINK/SUI/XRP/ONDO "
        "that live trading blocks because mid-cap allow_short=False."
    )
    result["accounting_note"] = (
        "Paper results are price-only gross return percentages; trading fees "
        "and funding are not included."
    )
    result.setdefault("bots", {})
    result.setdefault("dual_short_confirmed_filter", {
        "scope": (
            "Shadow-only subset: mid-cap enter_short signals counted only when "
            "BTC and ETH are both confirmed short in the same strategy snapshot."
        ),
        "accounting_note": (
            "Hypothetical price-only gross returns; trading fees and funding excluded."
        ),
        "bots": {},
    })
    result["errors"] = []

    configs = {
        "aggressive": {
            "interval": "30m",
            "lookback_hours": 1000,
            "generate": generate_aggressive_signals,
            "classify": classify_aggressive_signal,
        },
        "intraday": {
            "interval": "1h",
            "lookback_hours": 1000,
            "generate": generate_intraday_signals,
            "classify": classify_intraday_signal,
        },
    }

    for bot_name, cfg in configs.items():
        bot_state = result["bots"].setdefault(
            bot_name,
            {"open_positions": {}, "closed_trades": []},
        )
        bot_state.setdefault("open_positions", {})
        bot_state.setdefault("closed_trades", [])
        filtered_state = result["dual_short_confirmed_filter"]["bots"].setdefault(
            bot_name, {"open_positions": {}, "closed_trades": []}
        )
        filtered_state.setdefault("open_positions", {})
        filtered_state.setdefault("closed_trades", [])

        try:
            all_data = fetch_all_intraday(
                ["BTC-USD", "ETH-USD"] + MIDCAP_SHORT_SHADOW_TICKERS,
                interval=cfg["interval"],
                lookback_hours=cfg["lookback_hours"],
            )
            direction = {}
            for major in ("BTC-USD", "ETH-USD"):
                major_df = all_data.get(major)
                if major_df is None or major_df.empty or len(major_df) < 50:
                    direction[major] = False
                    continue
                major_sig = cfg["generate"](major_df, allow_short=True)
                direction[major] = int(major_sig["Signal"].iloc[-1]) == -1
            dual_short_confirmed = bool(
                direction.get("BTC-USD") and direction.get("ETH-USD")
            )
        except Exception as exc:
            result["errors"].append(
                f"{bot_name}: data fetch failed: {type(exc).__name__}: {exc}"
            )
            continue

        for ticker in MIDCAP_SHORT_SHADOW_TICKERS:
            asset = HL_SYMBOL_MAP.get(ticker, ticker)
            try:
                df = all_data.get(ticker)
                if df is None or df.empty or len(df) < 50:
                    continue

                signal_df = cfg["generate"](df, allow_short=True)
                last_signal = int(signal_df["Signal"].iloc[-1])
                prev_signal = int(signal_df["Signal"].iloc[-2])
                action = cfg["classify"](last_signal, prev_signal)
                price = float(df["Close"].iloc[-1])
                candle_time = df.index[-1]
                if hasattr(candle_time, "isoformat"):
                    candle_time = candle_time.isoformat()
                else:
                    candle_time = str(candle_time)

                open_pos = bot_state["open_positions"].get(asset)
                filtered_pos = filtered_state["open_positions"].get(asset)

                # Filtered shadow cohort: a fresh mid-cap short is admitted only
                # when BOTH BTC and ETH are concurrently confirmed short by the
                # same bot strategy. It never sends a live order.
                if (
                    filtered_pos is None
                    and action == "enter_short"
                    and dual_short_confirmed
                ):
                    filtered_state["open_positions"][asset] = {
                        "asset": asset,
                        "ticker": ticker,
                        "entry_time": candle_time,
                        "entry_price": price,
                        "btc_confirmed_short": True,
                        "eth_confirmed_short": True,
                        "filter": "BTC+ETH confirmed short + mid-cap enter_short",
                        "current_price": price,
                        "unrealized_gross_return_pct": 0.0,
                    }
                    filtered_pos = filtered_state["open_positions"][asset]

                if filtered_pos is not None:
                    f_entry = float(filtered_pos.get("entry_price", 0.0) or 0.0)
                    filtered_pos["current_price"] = price
                    filtered_pos["unrealized_gross_return_pct"] = round(
                        _shadow_return_pct(f_entry, price), 4
                    )
                    if last_signal != -1:
                        f_ret = _shadow_return_pct(f_entry, price)
                        filtered_state["closed_trades"].append({
                            "asset": asset,
                            "ticker": ticker,
                            "entry_time": filtered_pos.get("entry_time"),
                            "exit_time": candle_time,
                            "entry_price": f_entry,
                            "exit_price": price,
                            "gross_return_pct": round(f_ret, 4),
                            "outcome": (
                                "win" if f_ret > 0 else
                                "loss" if f_ret < 0 else "breakeven"
                            ),
                            "exit_action": action,
                            "filter": "BTC+ETH confirmed short + mid-cap enter_short",
                        })
                        filtered_state["open_positions"].pop(asset, None)

                if open_pos is None and action == "enter_short":
                    bot_state["open_positions"][asset] = {
                        "asset": asset,
                        "ticker": ticker,
                        "entry_time": candle_time,
                        "entry_price": price,
                        "blocked_live_reason": "mid-cap allow_short=False",
                        "current_price": price,
                        "unrealized_gross_return_pct": 0.0,
                    }
                    continue

                if open_pos is None:
                    continue

                entry_price = float(open_pos.get("entry_price", 0.0) or 0.0)
                open_pos["current_price"] = price
                open_pos["unrealized_gross_return_pct"] = round(
                    _shadow_return_pct(entry_price, price),
                    4,
                )

                if last_signal != -1:
                    gross_return_pct = _shadow_return_pct(entry_price, price)
                    closed = {
                        "asset": asset,
                        "ticker": ticker,
                        "entry_time": open_pos.get("entry_time"),
                        "exit_time": candle_time,
                        "entry_price": entry_price,
                        "exit_price": price,
                        "gross_return_pct": round(gross_return_pct, 4),
                        "outcome": (
                            "win" if gross_return_pct > 0
                            else "loss" if gross_return_pct < 0
                            else "breakeven"
                        ),
                        "exit_action": action,
                        "blocked_live_reason": "mid-cap allow_short=False",
                    }
                    bot_state["closed_trades"].append(closed)
                    bot_state["open_positions"].pop(asset, None)

            except Exception as exc:
                result["errors"].append(
                    f"{bot_name}/{asset}: {type(exc).__name__}: {exc}"
                )

        bot_state["closed_trades"] = bot_state["closed_trades"][-200:]
        filtered_state["closed_trades"] = filtered_state["closed_trades"][-200:]
        filtered_today = [
            r for r in filtered_state["closed_trades"]
            if str(r.get("exit_time", "")).startswith(now.date().isoformat())
        ]
        filtered_state["today"] = _shadow_stats(filtered_today)
        filtered_state["all_time"] = _shadow_stats(filtered_state["closed_trades"])
        filtered_state["btc_confirmed_short_now"] = bool(direction.get("BTC-USD"))
        filtered_state["eth_confirmed_short_now"] = bool(direction.get("ETH-USD"))
        filtered_state["dual_short_confirmed_now"] = dual_short_confirmed

        today_rows = [
            r for r in bot_state["closed_trades"]
            if str(r.get("exit_time", "")).startswith(now.date().isoformat())
        ]
        bot_state["today"] = _shadow_stats(today_rows)
        bot_state["all_time"] = _shadow_stats(bot_state["closed_trades"])

    return result


def _fetch_gist_file(gist_id: str, filename: str, token: str) -> dict[str, Any]:
    resp = requests.get(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"token {token}"},
        timeout=20,
    )
    resp.raise_for_status()
    files = resp.json().get("files", {})
    item = files.get(filename)
    if not item:
        raise RuntimeError(f"{filename} not found in Gist {gist_id}")

    content = item.get("content", "")
    if item.get("truncated"):
        raw_url = item.get("raw_url")
        if not raw_url:
            raise RuntimeError(f"{filename} is truncated and has no raw_url")
        raw = requests.get(
            raw_url,
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.raw",
            },
            timeout=30,
        )
        raw.raise_for_status()
        content = raw.text

    state = json.loads(content)
    if not isinstance(state, dict):
        raise RuntimeError(f"{filename} is not a JSON object")
    return state


def _timestamp(item: dict[str, Any]) -> dt.datetime | None:
    raw = item.get("timestamp")
    if raw:
        try:
            return dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(dt.UTC)
        except (TypeError, ValueError):
            pass
    ms = item.get("fill_time_ms")
    if ms:
        try:
            return dt.datetime.fromtimestamp(int(ms) / 1000, tz=dt.UTC)
        except (TypeError, ValueError, OSError):
            pass
    return None


def _num(item: dict[str, Any], key: str) -> float:
    try:
        return float(item.get(key, 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _trade_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    wins = [r for r in rows if _num(r, "realized_pnl") > 0]
    losses = [r for r in rows if _num(r, "realized_pnl") < 0]
    decided = len(wins) + len(losses)
    return {
        "trades": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(rows) - decided,
        "win_rate_pct": round(len(wins) / decided * 100.0, 2) if decided else None,
        "average_win": round(sum(_num(r, "realized_pnl") for r in wins) / len(wins), 6) if wins else None,
        "average_loss": round(sum(_num(r, "realized_pnl") for r in losses) / len(losses), 6) if losses else None,
        "net_pnl": round(sum(_num(r, "realized_pnl") for r in rows), 6),
        "profit_giveback": round(sum(_num(r, "profit_giveback") for r in rows), 6),
    }


def _group(rows: list[dict[str, Any]], key_fn) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = key_fn(row)
        if key is None or key == "":
            continue
        groups.setdefault(str(key), []).append(row)
    return {k: _trade_stats(v) for k, v in sorted(groups.items())}


def _max_closed_trade_drawdown(rows: list[dict[str, Any]]) -> float:
    ordered = sorted(rows, key=lambda r: _timestamp(r) or dt.datetime.min.replace(tzinfo=dt.UTC))
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for row in ordered:
        cumulative += _num(row, "realized_pnl")
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)
    return round(max_dd, 6)


def _summarize(name: str, state: dict[str, Any], day: dt.date) -> dict[str, Any]:
    history = state.get("history", []) or []
    today_rows = [r for r in history if (_timestamp(r) and _timestamp(r).date() == day)]

    closes = [
        r for r in today_rows
        if r.get("action") == "close"
        and r.get("status") == "filled"
        and r.get("realized_pnl") is not None
    ]

    gross = sum(_num(r, "gross_closed_pnl") for r in closes)
    fees = sum(_num(r, "trading_fees") for r in closes)
    funding = sum(_num(r, "funding_pnl") for r in closes)
    net = sum(_num(r, "realized_pnl") for r in closes)

    closed_trades = []
    for r in closes:
        closed_trades.append({
            "time": (_timestamp(r).isoformat() if _timestamp(r) else None),
            "asset": r.get("hl_coin") or r.get("ticker"),
            "side": r.get("side"),
            "realized_net_pnl": round(_num(r, "realized_pnl"), 6),
            "gross_pnl": round(_num(r, "gross_closed_pnl"), 6),
            "trading_fees": round(_num(r, "trading_fees"), 6),
            "funding": round(_num(r, "funding_pnl"), 6),
            "leverage": r.get("entry_leverage") or r.get("leverage"),
            "entry_quality": r.get("entry_quality"),
            "entry_type": r.get("entry_type"),
            "shadow_fresh_only_would_block": r.get("shadow_fresh_only_would_block"),
            "shadow_bearish_regime_evaluable": r.get("shadow_bearish_regime_evaluable"),
            "shadow_bearish_regime_would_block": r.get("shadow_bearish_regime_would_block"),
            "shadow_combined_would_block": r.get("shadow_combined_would_block"),
            "shadow_market_regime": r.get("shadow_market_regime"),
            "shadow_dynamic_leverage": r.get("shadow_dynamic_leverage"),
            "shadow_dual_short_btc_short": r.get("shadow_dual_short_btc_short"),
            "shadow_dual_short_eth_short": r.get("shadow_dual_short_eth_short"),
            "shadow_dual_short_long_block_would_block": r.get("shadow_dual_short_long_block_would_block"),
            "exit_type": r.get("exit_type"),
            "protection_mode": r.get("protection_mode"),
            "peak_unrealized_pnl": r.get("peak_unrealized_pnl"),
            "profit_giveback": r.get("profit_giveback"),
            "fee_data_complete": r.get("fee_data_complete"),
            "funding_data_complete": r.get("funding_data_complete"),
            "pnl_source": r.get("pnl_source"),
        })

    incomplete = [
        {
            "asset": r.get("hl_coin") or r.get("ticker"),
            "fee_data_complete": r.get("fee_data_complete"),
            "funding_data_complete": r.get("funding_data_complete"),
            "pnl_source": r.get("pnl_source"),
        }
        for r in closes
        if r.get("fee_data_complete") is False or r.get("funding_data_complete") is False
        or str(r.get("pnl_source", "")).startswith("price_fallback")
    ]

    errors = [
        {k: r.get(k) for k in ("timestamp", "ticker", "hl_coin", "action", "status", "error", "reason")}
        for r in today_rows
        if r.get("status") in ("error", "unknown") or r.get("error")
    ]
    skipped = [
        {k: r.get(k) for k in ("timestamp", "ticker", "hl_coin", "action", "status", "reason")}
        for r in today_rows if r.get("status") == "skipped"
    ]
    safety = [
        {k: r.get(k) for k in ("timestamp", "ticker", "hl_coin", "action", "status", "reason", "exit_type")}
        for r in today_rows
        if any(word in str(r.get("reason", "")).lower() for word in (
            "lock", "drawdown", "kill", "minimum", "safety", "blocked"
        ))
    ]

    protection = [
        t for t in closed_trades
        if str(t.get("exit_type", "")).upper() == "PROFIT PROTECTION"
        or "protection" in str(t.get("protection_mode", "")).lower()
    ]

    result = {
        "realized_net_pnl": round(net, 6),
        "gross_closed_pnl": round(gross, 6),
        "trading_fees": round(fees, 6),
        "funding": round(funding, 6),
        "stats": _trade_stats(closes),
        "closed_trades": closed_trades,
        "by_asset": _group(closes, lambda r: r.get("hl_coin") or r.get("ticker")),
        "profit_giveback": round(sum(_num(r, "profit_giveback") for r in closes), 6),
        "closed_trade_max_drawdown": _max_closed_trade_drawdown(closes),
        "bot_state_drawdown_pct": state.get("last_bot_dd_pct"),
        "profit_protection_exits": protection,
        "errors": errors,
        "skipped_orders": skipped,
        "safety_events": safety,
        "incomplete_accounting": incomplete,
        "last_run": state.get("last_run"),
        "last_strategy_run": state.get("last_strategy_run", state.get("last_run")),
        "last_protection_run": state.get("last_protection_run"),
    }

    if name == "aggressive":
        result["leverage_results"] = _group(
            closes,
            lambda r: f"{float(r.get('entry_leverage') or r.get('leverage')):g}x"
            if (r.get("entry_leverage") is not None or r.get("leverage") is not None) else None,
        )
        result["profit_retention_shadow"] = state.get("aggressive_profit_retention_shadow", {})
        result["entry_quality_results"] = _group(closes, lambda r: r.get("entry_quality"))
        result["entry_type_results"] = _group(
            closes,
            lambda r: (
                "sync" if str(r.get("entry_type", "")).startswith("sync_")
                else "fresh" if r.get("entry_type") else None
            ),
        )
        result["dynamic_leverage_shadow_results"] = {
            "rule": "1x strong bearish; 2x bearish; 3x mixed; 4x bullish; 5x strong bullish",
            "by_regime": _group(closes, lambda r: r.get("shadow_market_regime")),
            "by_shadow_leverage": _group(
                closes,
                lambda r: (
                    f"{float(r.get('shadow_dynamic_leverage')):g}x"
                    if r.get("shadow_dynamic_leverage") is not None else None
                ),
            ),
            "tagged_trades": sum(
                1 for r in closes if r.get("shadow_dynamic_leverage") is not None
            ),
            "observation_only": True,
        }
        result["dual_short_long_block_shadow_results"] = {
            "rule": (
                "shadow-only: block NEW SOL/AVAX/LINK/SUI/XRP/ONDO longs "
                "when Aggressive owns both BTC and ETH shorts"
            ),
            "would_allow": _trade_stats([
                r for r in closes
                if r.get("shadow_dual_short_long_block_would_block") is False
            ]),
            "would_block": _trade_stats([
                r for r in closes
                if r.get("shadow_dual_short_long_block_would_block") is True
            ]),
            "tagged_trades": sum(
                1 for r in closes
                if r.get("shadow_dual_short_long_block_would_block") is not None
            ),
            "observation_only": True,
        }
        result["entry_filter_shadow_results"] = {
            "fresh_only": {
                "would_allow": _trade_stats([
                    r for r in closes
                    if r.get("shadow_fresh_only_would_block") is False
                ]),
                "would_block": _trade_stats([
                    r for r in closes
                    if r.get("shadow_fresh_only_would_block") is True
                ]),
            },
            "bearish_regime_long_filter": {
                "rule": "block long when ADX>=15, -DI>+DI, and price is below 20-bar rolling VWAP",
                "would_allow": _trade_stats([
                    r for r in closes
                    if r.get("shadow_bearish_regime_evaluable") is True
                    and r.get("shadow_bearish_regime_would_block") is False
                ]),
                "would_block": _trade_stats([
                    r for r in closes
                    if r.get("shadow_bearish_regime_would_block") is True
                ]),
            },
            "combined": {
                "would_allow": _trade_stats([
                    r for r in closes
                    if r.get("shadow_combined_would_block") is False
                ]),
                "would_block": _trade_stats([
                    r for r in closes
                    if r.get("shadow_combined_would_block") is True
                ]),
            },
            "observation_only": True,
        }

    return result


def main() -> None:
    token = os.environ.get("GIST_TOKEN")
    if not token:
        raise RuntimeError("GIST_TOKEN is required")

    now = dt.datetime.now(dt.UTC)
    day = now.date()
    previous_short_shadow = _load_previous_short_shadow()

    report: dict[str, Any] = {
        "schema_version": 2,
        "date_utc": day.isoformat(),
        "generated_at": now.isoformat(),
        "reporting_only": True,
        "bots": {},
        "report_errors": [],
    }

    for name, (env_name, filename) in BOTS.items():
        gist_id = os.environ.get(env_name)
        if not gist_id:
            report["report_errors"].append(f"{name}: missing {env_name}")
            continue
        try:
            state = _fetch_gist_file(gist_id, filename, token)
            report["bots"][name] = _summarize(name, state, day)
        except Exception as exc:
            report["report_errors"].append(f"{name}: {type(exc).__name__}: {exc}")

    try:
        report["short_opportunity_check"] = _update_short_opportunity_check(
            previous_short_shadow,
            now,
        )
    except Exception as exc:
        report["short_opportunity_check"] = previous_short_shadow
        report["report_errors"].append(
            f"short opportunity tracking: {type(exc).__name__}: {exc}"
        )

    out = Path("reports")
    out.mkdir(exist_ok=True)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    (out / "latest.json").write_text(payload, encoding="utf-8")
    (out / f"{day.isoformat()}.json").write_text(payload, encoding="utf-8")
    print(f"Wrote reporting snapshot for {day.isoformat()}")


if __name__ == "__main__":
    main()
