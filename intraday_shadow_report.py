"""
intraday_shadow_report.py — read-only live shadow monitor for Intraday exits.

This script NEVER creates an Exchange client and is intentionally run without
HL_PRIVATE_KEY. It cannot place, close, resize, or modify an order.

It compares currently owned Intraday positions against three research ideas:
  1) DMI adverse direction + ADX(14) < 20 while the live oscillator is FLAT
  2) 1.5 x ATR trailing-stop trigger
  3) Donchian-20 trigger for LINK only

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