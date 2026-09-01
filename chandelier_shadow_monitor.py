"""Read-only Chandelier Exit shadow monitor for Intraday positions.

Research only. This script never creates an Exchange client and never receives
HL_PRIVATE_KEY, so it cannot place, close, resize, or modify an order.

Rule under test:
- ATR(14), Wilder smoothing, using completed 1h candles.
- Long: highest high observed since entry - 2.0 * ATR.
- Short: lowest low observed since entry + 2.0 * ATR.
- The stop ratchets only in the profitable direction and never loosens.
- A close beyond the ratcheted level is recorded as a hypothetical EXIT.
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

STATE_FILENAME = "intraday_state.json"
LOOKBACK_HOURS = 1000
ATR_PERIOD = 14
CHAND_MULT = 2.0

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
    resp.raise_for_status()
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
    is_testnet = os.environ.get("HL_TESTNET", "true").lower() == "true"
    base_url = constants.TESTNET_API_URL if is_testnet else constants.MAINNET_API_URL
    return Info(base_url, skip_ws=True), address


def get_open_positions(info: Info, address: str, owned: set[str]) -> dict:
    positions = {}
    for item in info.user_state(address).get("assetPositions", []):
        pos = item.get("position", {})
        size = float(pos.get("szi", 0.0) or 0.0)
        coin = str(pos.get("coin"))
        if size == 0 or coin not in owned:
            continue
        positions[coin] = {
            "size": size,
            "entry_px": float(pos.get("entryPx", 0.0) or 0.0),
            "unrealized_pnl": float(pos.get("unrealizedPnl", 0.0) or 0.0),
        }
    return positions


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
                return int(fill_ms)
            except (TypeError, ValueError):
                pass
    return None


def atr_wilder(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def candle_times_ms(index: pd.Index) -> np.ndarray:
    timestamps = pd.to_datetime(index, utc=True)
    return (timestamps.astype("int64") // 1_000_000).to_numpy()


def chandelier_level(
    df: pd.DataFrame,
    side: str,
    entry_px: float,
    opened_ms: int | None,
    previous_level: float | None,
) -> tuple[str, float | None, float | None, bool]:
    atr_series = atr_wilder(df)
    atr_now = float(atr_series.iloc[-1]) if len(atr_series) else float("nan")
    if not np.isfinite(atr_now) or atr_now <= 0:
        return "N/A", previous_level, None, False

    start_idx = len(df) - 1
    partial_history = False
    if opened_ms is not None:
        times_ms = candle_times_ms(df.index)
        matches = np.flatnonzero(times_ms >= opened_ms)
        if len(matches):
            start_idx = int(matches[0])
        else:
            partial_history = True
    else:
        partial_history = True

    held = df.iloc[start_idx:]
    if held.empty:
        held = df.iloc[-1:]
        partial_history = True

    current = float(df["Close"].iloc[-1])
    if side == "long":
        highest = max(float(entry_px), float(held["High"].astype(float).max()))
        raw = highest - CHAND_MULT * atr_now
        level = raw if previous_level is None else max(float(previous_level), raw)
        decision = "EXIT" if current <= level else "HOLD"
    else:
        lowest = min(float(entry_px), float(held["Low"].astype(float).min()))
        raw = lowest + CHAND_MULT * atr_now
        level = raw if previous_level is None else min(float(previous_level), raw)
        decision = "EXIT" if current >= level else "HOLD"

    return decision, float(level), atr_now, partial_history


def send_telegram(lines: list[str]) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    raw_ids = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not raw_ids:
        return
    text = "\n".join(lines)
    for chat_id in [x.strip() for x in raw_ids.split(",") if x.strip()]:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=15,
        )
        resp.raise_for_status()


def main() -> None:
    now = dt.datetime.now(dt.UTC)
    print(f"Chandelier shadow started at {now.isoformat()}")
    print("READ ONLY: no private key, no Exchange client, no order methods")

    state = load_state()
    info, address = get_info_and_address()
    owned = set(state.get("owned_coins", []) or [])
    positions = get_open_positions(info, address, owned)
    data = fetch_all_intraday(TICKERS, interval="1h", lookback_hours=LOOKBACK_HOURS)
    ticker_by_coin = {coin: ticker for ticker, coin in HL_SYMBOL_MAP.items() if ticker in TICKERS}

    active = {
        str(k): dict(v)
        for k, v in (state.get("shadow_chandelier_active", {}) or {}).items()
        if isinstance(v, dict)
    }
    history = list(state.get("shadow_chandelier_history", []) or [])
    last_signatures = dict(state.get("shadow_chandelier_last_signature", {}) or {})
    new_signatures = {}
    lines = ["🧪 Crypto Y'all Chandelier Shadow", "Observation only — no order placed", ""]

    for coin, pos in sorted(positions.items()):
        ticker = ticker_by_coin.get(coin)
        df = data.get(ticker) if ticker else None
        if df is None or df.empty or len(df) < ATR_PERIOD + 2:
            continue

        side = "long" if float(pos["size"]) > 0 else "short"
        entry_px = float(pos["entry_px"])
        prior = active.get(coin)
        if prior and (prior.get("side") != side or abs(float(prior.get("entry_px", entry_px)) - entry_px) > 1e-12):
            prior = None

        previous_level = float(prior["level"]) if prior and prior.get("level") is not None else None
        decision, level, atr_now, partial = chandelier_level(
            df, side, entry_px, position_open_ms(state, coin), previous_level
        )
        current = float(df["Close"].iloc[-1])

        active[coin] = {
            "ticker": ticker,
            "side": side,
            "entry_px": entry_px,
            "level": level,
            "last_seen_at": now.isoformat(),
        }
        snapshot = {
            "timestamp": now.isoformat(),
            "ticker": ticker,
            "coin": coin,
            "side": side,
            "entry_px": entry_px,
            "price": current,
            "unrealized_pnl": float(pos["unrealized_pnl"]),
            "chandelier_atr_period": ATR_PERIOD,
            "chandelier_atr_mult": CHAND_MULT,
            "chandelier_atr": atr_now,
            "chandelier_level": level,
            "chandelier_decision": decision,
            "chandelier_history_partial": partial,
        }
        history.append(snapshot)

        signature = f"{side}|{decision}|{level:.10f}" if level is not None else f"{side}|{decision}|none"
        new_signatures[coin] = signature
        print(
            f"Chandelier {coin} {side.upper()} decision={decision} "
            f"level={level} ATR={atr_now} PnL={pos['unrealized_pnl']:+.4f}"
        )

        previous_signature = last_signatures.get(coin)
        previous_decision = previous_signature.split("|")[1] if previous_signature and "|" in previous_signature else None
        # Telegram only on first observation or decision change; level movements are still persisted.
        if previous_decision != decision:
            lines.append(f"{coin} {side.upper()} @ ${current:,.4f}")
            level_text = "N/A" if level is None else f"${level:,.4f}"
            lines.append(f"  Chandelier 2ATR: {decision} | level {level_text}")
            if partial:
                lines.append("  History: partial since-entry data")
            lines.append("")

    active = {k: v for k, v in active.items() if k in positions}
    state["shadow_chandelier_active"] = active
    state["shadow_chandelier_history"] = history[-1000:]
    state["shadow_chandelier_last_signature"] = new_signatures
    save_state(state)

    if len(lines) > 3:
        lines.append(now.strftime("%Y-%m-%d %H:%M UTC"))
        send_telegram(lines)
        print("Chandelier Telegram sent: decision change detected")
    else:
        print("Chandelier Telegram not sent: no decision changes")

    print("Chandelier shadow done")


if __name__ == "__main__":
    main()
