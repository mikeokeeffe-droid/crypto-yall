"""Read-only Aggressive exit shadow suite.

Runs ATR1.5, RSI(14) 70/30 reversal, and Chandelier 2ATR on completed
30-minute candles for positions owned by the Aggressive bot. Observation only:
there is no private key, Exchange client, or order method in this script.
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
from rsi_shadow_exit import rsi_reversal_shadow

STATE_FILENAME = "aggressive_state.json"
ATR_PERIOD = 14
ATR_MULT = 1.5
CHAND_MULT = 2.0
LOOKBACK_HOURS = 1000
TICKERS = list(HL_SYMBOL_MAP.keys())


def load_state() -> dict:
    token = os.environ.get("GIST_TOKEN")
    gist_id = os.environ.get("AGGRESSIVE_GIST_ID")
    if not token or not gist_id:
        raise RuntimeError("GIST_TOKEN or AGGRESSIVE_GIST_ID missing")
    resp = requests.get(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"token {token}"},
        timeout=15,
    )
    resp.raise_for_status()
    files = resp.json().get("files", {})
    if STATE_FILENAME not in files:
        raise RuntimeError(f"{STATE_FILENAME} missing from Aggressive Gist")
    state = json.loads(files[STATE_FILENAME]["content"])
    if not isinstance(state, dict):
        raise RuntimeError("Aggressive state is not a JSON object")
    return state


def save_state(state: dict) -> None:
    token = os.environ.get("GIST_TOKEN")
    gist_id = os.environ.get("AGGRESSIVE_GIST_ID")
    resp = requests.patch(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"token {token}"},
        json={"files": {STATE_FILENAME: {"content": json.dumps(state, indent=2)}}},
        timeout=15,
    )
    resp.raise_for_status()


def get_info_and_address() -> tuple[Info, str]:
    address = os.environ.get("HL_ACCOUNT_ADDRESS")
    if not address:
        raise RuntimeError("HL_ACCOUNT_ADDRESS missing")
    testnet = os.environ.get("HL_TESTNET", "false").lower() == "true"
    url = constants.TESTNET_API_URL if testnet else constants.MAINNET_API_URL
    return Info(url, skip_ws=True), address


def get_positions(info: Info, address: str) -> dict:
    raw = info.user_state(address)
    out = {}
    for item in raw.get("assetPositions", []):
        p = item.get("position", {})
        size = float(p.get("szi", 0.0) or 0.0)
        if size == 0:
            continue
        out[str(p.get("coin"))] = {
            "size": size,
            "entry_px": float(p.get("entryPx", 0.0) or 0.0),
            "unrealized_pnl": float(p.get("unrealizedPnl", 0.0) or 0.0),
        }
    return out


def atr_wilder(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    prev_close = df["Close"].shift(1)
    tr = pd.concat(
        [
            (df["High"] - df["Low"]).abs(),
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def latest_open_time(state: dict, coin: str) -> pd.Timestamp | None:
    for rec in reversed(state.get("history", []) or []):
        if str(rec.get("hl_coin", "")) != coin:
            continue
        if str(rec.get("action", "")) == "close" and str(rec.get("status", "")).lower() == "filled":
            break
        action = str(rec.get("action", ""))
        if action in {"open_long", "open_short"} and str(rec.get("status", "")).lower() == "filled":
            try:
                return pd.Timestamp(rec.get("timestamp")).tz_convert(None)
            except Exception:
                try:
                    return pd.Timestamp(rec.get("timestamp")).tz_localize(None)
                except Exception:
                    return None
    return None


def same_trade(previous: dict, side: str, entry_px: float) -> bool:
    if not previous:
        return False
    if str(previous.get("side", "")).lower() != side:
        return False
    try:
        old_entry = float(previous.get("entry_px", 0.0) or 0.0)
    except (TypeError, ValueError):
        return False
    tolerance = max(1e-12, abs(entry_px) * 1e-8)
    return abs(old_entry - entry_px) <= tolerance


def main() -> None:
    print("Aggressive exit shadow suite started")
    print("READ ONLY: no private key, no Exchange client, no order methods")
    state = load_state()
    info, address = get_info_and_address()
    positions = get_positions(info, address)
    owned = set(state.get("owned_coins", []) or [])
    managed = {c: p for c, p in positions.items() if c in owned}
    shadow = state.setdefault("aggressive_exit_shadow", {})
    rsi_armed = state.setdefault("aggressive_rsi_armed", {})

    # Remove state for positions that are no longer owned/open so a future
    # trade in the same coin always starts with a clean shadow trail.
    for coin in list(shadow):
        if coin not in managed:
            shadow.pop(coin, None)
    for coin in list(rsi_armed):
        if coin not in managed:
            rsi_armed.pop(coin, None)

    if not managed:
        state["aggressive_exit_shadow"] = shadow
        state["aggressive_rsi_armed"] = rsi_armed
        save_state(state)
        print("No Aggressive-owned open positions")
        return

    data = fetch_all_intraday(TICKERS, interval="30m", lookback_hours=LOOKBACK_HOURS)
    ticker_by_coin = {coin: ticker for ticker, coin in HL_SYMBOL_MAP.items()}

    for coin, pos in managed.items():
        ticker = ticker_by_coin.get(coin)
        df = data.get(ticker) if ticker else None
        if df is None or len(df) < ATR_PERIOD + 3:
            print(f"{coin}: insufficient 30m history")
            continue

        side = "long" if float(pos["size"]) > 0 else "short"
        entry = float(pos.get("entry_px", 0.0) or 0.0)
        current = float(df["Close"].iloc[-1])
        atr = atr_wilder(df)
        atr_now = float(atr.iloc[-1]) if np.isfinite(atr.iloc[-1]) else None
        if atr_now is None:
            print(f"{coin}: ATR unavailable")
            continue

        previous = shadow.get(coin, {}) if isinstance(shadow.get(coin), dict) else {}
        continuing = same_trade(previous, side, entry)
        if not continuing:
            # New position, side flip, or materially different entry: never
            # inherit ATR/Chandelier ratchets or RSI armed state from old trade.
            previous = {}
            rsi_armed[coin] = False
            print(f"{coin}: starting fresh shadow state for new {side} trade")

        open_time = latest_open_time(state, coin)
        if open_time is not None:
            since = df[df.index >= open_time]
            partial = len(since) == 0
        else:
            since = df.iloc[-1:]
            partial = True
        if len(since) == 0:
            since = df.iloc[-1:]
            partial = True

        # Match Intraday's reference rules: the entry itself is always a valid
        # favorable extreme, then completed since-entry candles can improve it.
        if side == "long":
            best_close = max(entry, float(since["Close"].max()))
            best_high = max(entry, float(since["High"].max()))
            atr_candidate = best_close - ATR_MULT * atr_now
            chand_candidate = best_high - CHAND_MULT * atr_now
        else:
            best_close = min(entry, float(since["Close"].min()))
            best_low = min(entry, float(since["Low"].min()))
            atr_candidate = best_close + ATR_MULT * atr_now
            chand_candidate = best_low + CHAND_MULT * atr_now

        prev_atr = previous.get("atr_level")
        prev_chand = previous.get("chandelier_level")
        if side == "long":
            atr_level = max(float(prev_atr), atr_candidate) if prev_atr is not None else atr_candidate
            chand_level = max(float(prev_chand), chand_candidate) if prev_chand is not None else chand_candidate
            atr_decision = "EXIT" if current <= atr_level else "HOLD"
            chand_decision = "EXIT" if current <= chand_level else "HOLD"
        else:
            atr_level = min(float(prev_atr), atr_candidate) if prev_atr is not None else atr_candidate
            chand_level = min(float(prev_chand), chand_candidate) if prev_chand is not None else chand_candidate
            atr_decision = "EXIT" if current >= atr_level else "HOLD"
            chand_decision = "EXIT" if current >= chand_level else "HOLD"

        rsi_decision, armed, rsi_now = rsi_reversal_shadow(
            df,
            side,
            bool(rsi_armed.get(coin, False)),
        )
        rsi_armed[coin] = bool(armed)

        size = abs(float(pos.get("size", 0.0) or 0.0))
        upnl = float(pos.get("unrealized_pnl", 0.0) or 0.0)
        ret = upnl / (entry * size) * 100.0 if entry > 0 and size > 0 else 0.0

        shadow[coin] = {
            "side": side,
            "entry_px": entry,
            "price": current,
            "return_pct": ret,
            "atr": atr_now,
            "atr_level": atr_level,
            "atr_decision": atr_decision,
            "rsi14": rsi_now,
            "rsi_armed": bool(armed),
            "rsi_decision": rsi_decision,
            "chandelier_level": chand_level,
            "chandelier_decision": chand_decision,
            "partial_history": partial,
            "updated_at": dt.datetime.now(dt.UTC).isoformat(),
        }

        print(
            f"{coin} {side.upper()} @ {current:.6g} | ret={ret:+.2f}% | "
            f"ATR1.5={atr_decision} level={atr_level:.6g} | "
            f"RSI14={rsi_now:.1f} armed={armed} {rsi_decision} | "
            f"Chandelier2ATR={chand_decision} level={chand_level:.6g} | "
            f"history={'partial' if partial else 'since-entry'}"
        )

    state["aggressive_exit_shadow"] = shadow
    state["aggressive_rsi_armed"] = rsi_armed
    save_state(state)
    print("Aggressive exit shadow suite done")


if __name__ == "__main__":
    main()
