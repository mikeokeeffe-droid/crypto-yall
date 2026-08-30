"""
intraday_shadow_report.py — read-only live shadow monitor for Intraday exits.

This script NEVER creates an Exchange client and is intentionally run without
HL_PRIVATE_KEY. It cannot place, close, resize, or modify an order.

It compares currently owned Intraday positions against three research ideas:
  1) DMI adverse direction + ADX(14) < 20 while the live oscillator is FLAT
  2) 1.5 x ATR trailing-stop trigger
  3) Donchian-20 trigger for LINK only

It also builds a passive FLAT-signal research dataset. For each owned position
that reaches signal=0 it records the first FLAT price/P&L, hourly FLAT checks,
ADX/DMI/ATR context, duration, and the eventual live outcome. This is research
only and never changes the live strategy.

The existing live Intraday strategy remains the source of truth for trading.
Shadow snapshots are stored in the Intraday Gist for later review. Telegram is
sent only when a position's shadow decision signature changes.
"""

from __future__ import annotations

import datetime as dt
import json
import os

import numpy as np
import pandas as pd
import requests
from hyperliquid.info import Info
from hyperliquid.utils import constants

from intraday_data_loader import fetch_all_intraday, HL_SYMBOL_MAP
from intraday_strategy import generate_intraday_signals, classify_intraday_signal
from backtester import get_asset_profile


STATE_FILENAME = "intraday_state.json"
LOOKBACK_HOURS = 1000
ADX_PERIOD = 14
ATR_TRAIL_MULT = 1.5
DONCHIAN_PERIOD = 20

TICKERS = [
    "BTC-USD",
    "ETH-USD",
    "SOL-USD",
    "AVAX-USD",
    "LINK-USD",
    "SUI20947-USD",
    "XRP-USD",
    "ONDO-USD",
]


def load_state() -> dict:
    token = os.environ.get("GIST_TOKEN")
    gist_id = os.environ.get("INTRADAY_GIST_ID")
    if not token or not gist_id:
        raise RuntimeError("GIST_TOKEN or INTRADAY_GIST_ID missing")

    resp = requests.get(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"token {token}"},
        timeout=15,
    )
    if not resp.ok:
        raise RuntimeError(
            f"Shadow state load failed: HTTP {resp.status_code} {resp.text}"
        )

    files = resp.json().get("files", {})
    if STATE_FILENAME not in files:
        raise RuntimeError(f"{STATE_FILENAME} missing from Intraday Gist")

    state = json.loads(files[STATE_FILENAME]["content"])
    if not isinstance(state, dict):
        raise RuntimeError("Intraday state is not a JSON object")
    return state


def save_state(state: dict) -> None:
    token = os.environ.get("GIST_TOKEN")
    gist_id = os.environ.get("INTRADAY_GIST_ID")
    if not token or not gist_id:
        raise RuntimeError("GIST_TOKEN or INTRADAY_GIST_ID missing")

    resp = requests.patch(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"token {token}"},
        json={"files": {STATE_FILENAME: {"content": json.dumps(state, indent=2)}}},
        timeout=15,
    )
    if not resp.ok:
        raise RuntimeError(
            f"Shadow state save failed: HTTP {resp.status_code} {resp.text}"
        )


def get_info_and_address() -> tuple[Info, str]:
    address = os.environ.get("HL_ACCOUNT_ADDRESS")
    if not address:
        raise RuntimeError("HL_ACCOUNT_ADDRESS missing")

    is_testnet = os.environ.get("HL_TESTNET", "true").lower() == "true"
    base_url = constants.TESTNET_API_URL if is_testnet else constants.MAINNET_API_URL
    return Info(base_url, skip_ws=True), address


def get_open_positions(info: Info, address: str) -> dict:
    """Read-only position snapshot from Hyperliquid."""
    user_state = info.user_state(address)
    positions = {}
    for item in user_state.get("assetPositions", []):
        pos = item.get("position", {})
        size = float(pos.get("szi", 0.0) or 0.0)
        if size == 0:
            continue
        positions[str(pos.get("coin"))] = {
            "size": size,
            "entry_px": float(pos.get("entryPx", 0.0) or 0.0),
            "unrealized_pnl": float(pos.get("unrealizedPnl", 0.0) or 0.0),
        }
    return positions


def dmi_wilder(df: pd.DataFrame, period: int = ADX_PERIOD) -> pd.DataFrame:
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)

    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=df.index,
        dtype=float,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=df.index,
        dtype=float,
    )

    atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_smoothed = plus_dm.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()
    minus_smoothed = minus_dm.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    plus_di = 100.0 * plus_smoothed / atr.replace(0, np.nan)
    minus_di = 100.0 * minus_smoothed / atr.replace(0, np.nan)
    denom = (plus_di + minus_di).replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / denom
    adx = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    return pd.DataFrame(
        {"PLUS_DI": plus_di, "MINUS_DI": minus_di, "ADX": adx},
        index=df.index,
    )


def position_open_ms(state: dict, coin: str) -> int | None:
    stored = (state.get("position_opened_at_ms", {}) or {}).get(coin)
    if stored is not None:
        try:
            value = int(stored)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass

    for item in reversed(state.get("history", []) or []):
        if item.get("hl_coin") != coin or item.get("status") != "filled":
            continue
        if item.get("action") == "close":
            break
        if item.get("action") not in ("open_long", "open_short"):
            continue

        fill_ms = item.get("fill_time_ms")
        if fill_ms is not None:
            try:
                value = int(fill_ms)
                if value > 0:
                    return value
            except (TypeError, ValueError):
                pass

        raw = item.get("timestamp")
        if raw:
            try:
                parsed = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=dt.UTC)
                return int(parsed.timestamp() * 1000)
            except (TypeError, ValueError):
                pass
    return None


def candle_times_ms(index: pd.Index) -> np.ndarray:
    timestamps = pd.to_datetime(index, utc=True)
    return (timestamps.astype("int64") // 1_000_000).to_numpy()


def atr_shadow(
    df: pd.DataFrame,
    sig: pd.DataFrame,
    side: str,
    entry_px: float,
    opened_ms: int | None,
) -> tuple[str, float | None, bool]:
    current_price = float(df["Close"].iloc[-1])
    atr_now = float(sig["ATR"].iloc[-1])
    if not np.isfinite(atr_now) or atr_now <= 0:
        return "N/A", None, False

    closes = df["Close"].astype(float).to_numpy()
    partial_history = False
    # Safe fallback: if no completed candle exists at/after the recorded open,
    # use only the latest completed candle instead of the full lookback history.
    start_idx = len(closes) - 1

    if opened_ms is not None:
        times_ms = candle_times_ms(df.index)
        matches = np.flatnonzero(times_ms >= opened_ms)
        if len(matches):
            start_idx = int(matches[0])
        else:
            partial_history = True
    else:
        partial_history = True

    held_closes = closes[start_idx:]
    if len(held_closes) == 0:
        held_closes = closes[-1:]
        partial_history = True

    if side == "long":
        best = max(float(entry_px), float(np.nanmax(held_closes)))
        trail = best - ATR_TRAIL_MULT * atr_now
        decision = "EXIT" if current_price <= trail else "HOLD"
    else:
        best = min(float(entry_px), float(np.nanmin(held_closes)))
        trail = best + ATR_TRAIL_MULT * atr_now
        decision = "EXIT" if current_price >= trail else "HOLD"

    return decision, float(trail), partial_history


def donchian_shadow(df: pd.DataFrame, side: str) -> tuple[str, float | None]:
    if len(df) <= DONCHIAN_PERIOD:
        return "N/A", None

    current_price = float(df["Close"].iloc[-1])
    previous = df.iloc[-(DONCHIAN_PERIOD + 1):-1]
    if side == "long":
        level = float(previous["Low"].min())
        return ("EXIT" if current_price < level else "HOLD"), level

    level = float(previous["High"].max())
    return ("EXIT" if current_price > level else "HOLD"), level


def parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.UTC)
        return parsed.astimezone(dt.UTC)
    except (TypeError, ValueError):
        return None


def latest_filled_close(state: dict, coin: str, started_at: str | None) -> dict | None:
    """Return the latest filled close for coin at/after a FLAT episode start."""
    started = parse_iso(started_at)
    for item in reversed(state.get("history", []) or []):
        if item.get("hl_coin") != coin:
            continue
        if item.get("action") != "close" or item.get("status") != "filled":
            continue

        item_time = parse_iso(item.get("timestamp"))
        if started is not None and item_time is not None and item_time < started:
            continue
        return item
    return None


def update_flat_research(
    state: dict,
    snapshots: list[dict],
    managed_coins: set[str],
    now: dt.datetime,
) -> None:
    """
    Build an observation-only dataset around signal=0 while positions are held.

    A FLAT episode starts the first time an owned position is observed with
    live_signal == 0. We save one sample per UTC hour so manual reruns do not
    inflate the dataset. The episode is finalized when the signal recovers or
    when the position is no longer owned/open. The comparison to first-FLAT P&L
    is intentionally labelled approximate because a hypothetical first-FLAT
    close would have its own closing fee/funding/slippage.
    """
    active = {
        str(k): dict(v)
        for k, v in (state.get("shadow_flat_active", {}) or {}).items()
        if isinstance(v, dict)
    }
    flat_history = list(state.get("shadow_flat_history", []) or [])
    completed = list(state.get("shadow_flat_completed", []) or [])
    hour_key = now.strftime("%Y-%m-%dT%H:00Z")

    for snapshot in snapshots:
        coin = str(snapshot["coin"])
        side = str(snapshot["side"])
        entry_px = float(snapshot["entry_px"])
        current_pnl = float(snapshot["unrealized_pnl"])
        is_flat_signal = int(snapshot.get("live_signal", 0)) == 0
        episode = active.get(coin)

        # Do not let a stale episode bleed into a newly opened/reversed trade.
        if episode is not None and (
            episode.get("side") != side
            or abs(float(episode.get("entry_px", entry_px)) - entry_px) > 1e-12
        ):
            completed.append({
                **episode,
                "ended_at": now.isoformat(),
                "end_reason": "position_changed",
            })
            active.pop(coin, None)
            episode = None

        if is_flat_signal:
            if episode is None:
                episode = {
                    "ticker": snapshot["ticker"],
                    "coin": coin,
                    "side": side,
                    "entry_px": entry_px,
                    "started_at": now.isoformat(),
                    "first_flat_price": float(snapshot["price"]),
                    "first_flat_unrealized_pnl": current_pnl,
                    "flat_checks": 0,
                    "last_counted_hour": None,
                }
                active[coin] = episode

            if episode.get("last_counted_hour") != hour_key:
                episode["flat_checks"] = int(episode.get("flat_checks", 0) or 0) + 1
                episode["last_counted_hour"] = hour_key
                new_hour = True
            else:
                new_hour = False

            started = parse_iso(episode.get("started_at"))
            flat_hours = (
                max(0.0, (now - started).total_seconds() / 3600.0)
                if started is not None
                else 0.0
            )
            first_pnl = float(episode.get("first_flat_unrealized_pnl", 0.0) or 0.0)
            pnl_change = current_pnl - first_pnl

            snapshot.update({
                "flat_signal": True,
                "flat_since": episode.get("started_at"),
                "flat_checks": int(episode.get("flat_checks", 0) or 0),
                "flat_hours": flat_hours,
                "first_flat_price": float(episode["first_flat_price"]),
                "first_flat_unrealized_pnl": first_pnl,
                "hold_vs_first_flat_pnl": pnl_change,
                "first_flat_exit_better_by": max(0.0, -pnl_change),
                "holding_better_by": max(0.0, pnl_change),
            })

            episode.update({
                "last_seen_at": now.isoformat(),
                "last_price": float(snapshot["price"]),
                "last_unrealized_pnl": current_pnl,
                "last_live_action": snapshot.get("live_action"),
                "last_adx": float(snapshot["adx"]),
                "last_dmi_adx20": snapshot.get("dmi_adx20"),
                "last_atr15": snapshot.get("atr15"),
            })

            if new_hour:
                flat_history.append({
                    "timestamp": now.isoformat(),
                    "ticker": snapshot["ticker"],
                    "coin": coin,
                    "side": side,
                    "entry_px": entry_px,
                    "price": float(snapshot["price"]),
                    "unrealized_pnl": current_pnl,
                    "live_action": snapshot.get("live_action"),
                    "flat_checks": int(episode["flat_checks"]),
                    "flat_since": episode["started_at"],
                    "flat_hours": flat_hours,
                    "first_flat_price": float(episode["first_flat_price"]),
                    "first_flat_unrealized_pnl": first_pnl,
                    "hold_vs_first_flat_pnl": pnl_change,
                    "first_flat_exit_better_by": max(0.0, -pnl_change),
                    "holding_better_by": max(0.0, pnl_change),
                    "adx": float(snapshot["adx"]),
                    "plus_di": float(snapshot["plus_di"]),
                    "minus_di": float(snapshot["minus_di"]),
                    "dmi_adx20": snapshot.get("dmi_adx20"),
                    "atr15": snapshot.get("atr15"),
                    "atr_trail_level": snapshot.get("atr_trail_level"),
                    "donchian20": snapshot.get("donchian20"),
                    "comparison_note": (
                        "First-FLAT comparison is approximate; hypothetical "
                        "exit fees/funding/slippage are not applied."
                    ),
                })
                print(
                    f"FLAT research: {coin} {side.upper()} "
                    f"check={episode['flat_checks']} "
                    f"hours={flat_hours:.1f} "
                    f"hold-vs-first-flat=${pnl_change:+.4f}"
                )

        else:
            snapshot["flat_signal"] = False
            if episode is not None:
                first_pnl = float(
                    episode.get("first_flat_unrealized_pnl", 0.0) or 0.0
                )
                pnl_change = current_pnl - first_pnl
                completed.append({
                    **episode,
                    "ended_at": now.isoformat(),
                    "end_reason": f"signal_{snapshot.get('live_action')}",
                    "end_price": float(snapshot["price"]),
                    "end_unrealized_pnl": current_pnl,
                    "hold_vs_first_flat_pnl": pnl_change,
                    "first_flat_exit_better_by": max(0.0, -pnl_change),
                    "holding_better_by": max(0.0, pnl_change),
                    "comparison_note": (
                        "Comparison uses unrealized P&L at observation points."
                    ),
                })
                active.pop(coin, None)
                snapshot["flat_episode_ended"] = True
                print(
                    f"FLAT research ended: {coin} "
                    f"reason={snapshot.get('live_action')} "
                    f"hold-vs-first-flat=${pnl_change:+.4f}"
                )

    # A position that disappeared since the previous shadow run was normally
    # closed by the real executor after the prior shadow observation. Pull the
    # live close result from normal Intraday history when available.
    for coin in list(active):
        if coin in managed_coins:
            continue

        episode = active.pop(coin)
        close = latest_filled_close(state, coin, episode.get("started_at"))
        outcome = {
            **episode,
            "ended_at": now.isoformat(),
            "end_reason": "position_no_longer_owned",
        }

        if close is not None:
            realized = close.get("realized_pnl")
            first_pnl = float(
                episode.get("first_flat_unrealized_pnl", 0.0) or 0.0
            )
            outcome.update({
                "end_reason": str(close.get("reason") or "live_close"),
                "live_close_timestamp": close.get("timestamp"),
                "live_close_price": close.get("fill_price"),
                "live_realized_pnl": realized,
                "live_gross_pnl": close.get("gross_closed_pnl"),
                "live_trading_fees": close.get("trading_fees"),
                "live_funding_pnl": close.get("funding_pnl"),
            })
            if realized is not None:
                approx_delta = float(realized) - first_pnl
                outcome.update({
                    "approx_live_vs_first_flat_pnl": approx_delta,
                    "approx_first_flat_exit_better_by": max(0.0, -approx_delta),
                    "approx_live_hold_better_by": max(0.0, approx_delta),
                    "comparison_note": (
                        "Approximate: live realized P&L includes actual fees/funding; "
                        "first-FLAT value is unrealized and does not include a "
                        "hypothetical closing fee/slippage."
                    ),
                })

        completed.append(outcome)
        print(
            f"FLAT research finalized: {coin} "
            f"reason={outcome.get('end_reason')}"
        )

    state["shadow_flat_active"] = active
    state["shadow_flat_history"] = flat_history[-1000:]
    state["shadow_flat_completed"] = completed[-250:]


def send_telegram(lines: list[str]) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    raw_ids = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not raw_ids:
        print("Shadow Telegram skipped: credentials missing")
        return

    text = "\n".join(lines)
    for chat_id in [x.strip() for x in raw_ids.split(",") if x.strip()]:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=15,
        )
        if not resp.ok:
            raise RuntimeError(
                f"Shadow Telegram failed: HTTP {resp.status_code} {resp.text}"
            )


def main() -> None:
    now = dt.datetime.now(dt.UTC)
    print(f"Intraday shadow monitor started at {now.isoformat()}")
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

    if not managed:
        update_flat_research(state, [], set(), now)
        state["last_shadow_snapshot"] = {
            "timestamp": now.isoformat(),
            "positions": [],
            "note": "No currently owned Intraday positions",
        }
        save_state(state)
        print("Shadow: no owned Intraday positions")
        return

    all_data = fetch_all_intraday(
        TICKERS,
        interval="1h",
        lookback_hours=LOOKBACK_HOURS,
    )

    ticker_by_coin = {
        coin: ticker
        for ticker, coin in HL_SYMBOL_MAP.items()
        if ticker in TICKERS
    }

    snapshots = []
    changed_lines = [
        "🧪 Crypto Y'all Intraday Shadow",
        "Observation only — no order placed",
        "",
    ]
    last_signatures = dict(state.get("shadow_last_signatures", {}) or {})
    new_signatures = dict(last_signatures)

    for coin in sorted(managed):
        ticker = ticker_by_coin.get(coin)
        df = all_data.get(ticker) if ticker else None
        if ticker is None or df is None or df.empty or len(df) < 50:
            print(f"Shadow skipped {coin}: candle data unavailable")
            continue

        pos = managed[coin]
        side = "long" if float(pos["size"]) > 0 else "short"
        profile = get_asset_profile(ticker)
        sig = generate_intraday_signals(
            df,
            allow_short=profile["allow_short"],
        )

        last_signal = int(sig["Signal"].iloc[-1])
        prev_signal = int(sig["Signal"].iloc[-2]) if len(sig) >= 2 else last_signal
        live_action = classify_intraday_signal(last_signal, prev_signal)
        current_price = float(df["Close"].iloc[-1])

        dmi = dmi_wilder(df)
        plus_di = float(dmi["PLUS_DI"].iloc[-1])
        minus_di = float(dmi["MINUS_DI"].iloc[-1])
        adx = float(dmi["ADX"].iloc[-1])

        strategy_flat = last_signal == 0
        adverse_dmi = (
            minus_di > plus_di if side == "long" else plus_di > minus_di
        )
        dmi_adx_exit = bool(
            strategy_flat
            and np.isfinite(adx)
            and adx < 20.0
            and adverse_dmi
        )
        dmi_decision = "EXIT" if dmi_adx_exit else "HOLD"

        opened_ms = position_open_ms(state, coin)
        atr_decision, atr_level, atr_partial = atr_shadow(
            df,
            sig,
            side,
            float(pos["entry_px"]),
            opened_ms,
        )

        if coin == "LINK":
            don_decision, don_level = donchian_shadow(df, side)
        else:
            don_decision, don_level = "N/A", None

        snapshot = {
            "timestamp": now.isoformat(),
            "ticker": ticker,
            "coin": coin,
            "side": side,
            "price": current_price,
            "entry_px": float(pos["entry_px"]),
            "unrealized_pnl": float(pos["unrealized_pnl"]),
            "live_action": live_action,
            "live_signal": last_signal,
            "dmi_adx20": dmi_decision,
            "plus_di": plus_di,
            "minus_di": minus_di,
            "adx": adx,
            "atr15": atr_decision,
            "atr_trail_level": atr_level,
            "atr_history_partial": atr_partial,
            "donchian20": don_decision,
            "donchian_level": don_level,
        }
        snapshots.append(snapshot)

        signature = "|".join(
            [live_action, dmi_decision, atr_decision, don_decision]
        )
        changed = last_signatures.get(coin) != signature
        new_signatures[coin] = signature

        print(
            f"Shadow {coin} {side.upper()} | live={live_action} | "
            f"DMI+ADX20={dmi_decision} (ADX={adx:.2f}, +DI={plus_di:.2f}, -DI={minus_di:.2f}) | "
            f"ATR1.5={atr_decision}"
            + (f" | Donchian20={don_decision}" if coin == "LINK" else "")
        )

        if changed:
            changed_lines.append(
                f"{coin} {side.upper()} @ ${current_price:,.4f}"
            )
            changed_lines.append(f"  Current: {live_action}")
            changed_lines.append(
                f"  DMI+ADX20: {dmi_decision} | ADX {adx:.1f}"
            )
            atr_text = f"  ATR1.5: {atr_decision}"
            if atr_level is not None:
                atr_text += f" | level ${atr_level:,.4f}"
            if atr_partial:
                atr_text += " | partial history"
            changed_lines.append(atr_text)
            if coin == "LINK":
                don_text = f"  Donchian20: {don_decision}"
                if don_level is not None:
                    don_text += f" | level ${don_level:,.4f}"
                changed_lines.append(don_text)
            changed_lines.append("")

    update_flat_research(state, snapshots, set(managed), now)

    # Remove alert signatures for positions no longer owned.
    for coin in list(new_signatures):
        if coin not in managed:
            new_signatures.pop(coin, None)

    history = list(state.get("shadow_history", []) or [])
    history.extend(snapshots)
    state["shadow_history"] = history[-500:]
    state["last_shadow_snapshot"] = {
        "timestamp": now.isoformat(),
        "positions": snapshots,
    }
    state["shadow_last_signatures"] = new_signatures
    save_state(state)

    if len(changed_lines) > 3:
        changed_lines.append(now.strftime("%Y-%m-%d %H:%M UTC"))
        send_telegram(changed_lines)
        print("Shadow Telegram sent: decision change detected")
    else:
        print("Shadow Telegram not sent: no decision changes")

    print("Intraday shadow monitor done")


if __name__ == "__main__":
    main()