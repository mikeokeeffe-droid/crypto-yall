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

    state_file = files[STATE_FILENAME]
    if state_file.get("truncated"):
        raw_url = state_file.get("raw_url")
        if not raw_url:
            raise RuntimeError(
                "Aggressive Gist state is truncated but has no raw_url"
            )
        raw_resp = requests.get(
            raw_url,
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.raw",
            },
            timeout=30,
        )
        raw_resp.raise_for_status()
        state_text = raw_resp.text
        print(
            "Aggressive exit shadow suite: state exceeded the inline Gist limit; "
            "loaded complete state from raw_url"
        )
    else:
        state_text = state_file.get("content", "")

    try:
        state = json.loads(state_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Aggressive state is invalid JSON: {e}") from e

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


def main() -> None:
    print("Aggressive exit shadow suite started")
    print("READ ONLY: no private key, no Exchange client, no order methods")
    state = load_state()
    info, address = get_info_and_address()
    positions = get_positions(info, address)
    owned = set(state.get("owned_coins", []) or [])
    managed = {c: p for c, p in positions.items() if c in owned}
    if not managed:
        print("No Aggressive-owned open positions")
        return

    data = fetch_all_intraday(TICKERS, interval="30m", lookback_hours=LOOKBACK_HOURS)
    ticker_by_coin = {coin: ticker for ticker, coin in HL_SYMBOL_MAP.items()}
    shadow = state.setdefault("aggressive_exit_shadow", {})
    rsi_armed = state.setdefault("aggressive_rsi_armed", {})
    retention = state.setdefault("aggressive_profit_retention_shadow", {})

    for coin, pos in managed.items():
        ticker = ticker_by_coin.get(coin)
        df = data.get(ticker) if ticker else None
        if df is None or len(df) < ATR_PERIOD + 3:
            print(f"{coin}: insufficient 30m history")
            continue

        side = "long" if float(pos["size"]) > 0 else "short"
        current = float(df["Close"].iloc[-1])
        atr = atr_wilder(df)
        atr_now = float(atr.iloc[-1]) if np.isfinite(atr.iloc[-1]) else None
        if atr_now is None:
            print(f"{coin}: ATR unavailable")
            continue

        # ATR1.5: one-sided volatility trail from the best close in the observed
        # since-entry window. This is research-only and ratchets through state.
        open_time = latest_open_time(state, coin)
        since = df[df.index >= open_time] if open_time is not None else df.tail(48)
        partial = open_time is None or len(since) == 0
        if len(since) == 0:
            since = df.tail(48)
        if side == "long":
            best_close = float(since["Close"].max())
            atr_candidate = best_close - ATR_MULT * atr_now
            best_high = float(since["High"].max())
            chand_candidate = best_high - CHAND_MULT * atr_now
        else:
            best_close = float(since["Close"].min())
            atr_candidate = best_close + ATR_MULT * atr_now
            best_low = float(since["Low"].min())
            chand_candidate = best_low + CHAND_MULT * atr_now

        prev = shadow.get(coin, {}) if isinstance(shadow.get(coin), dict) else {}
        prev_atr = prev.get("atr_level")
        prev_chand = prev.get("chandelier_level")
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

        entry = float(pos.get("entry_px", 0.0) or 0.0)
        size = abs(float(pos.get("size", 0.0) or 0.0))
        upnl = float(pos.get("unrealized_pnl", 0.0) or 0.0)
        ret = upnl / (entry * size) * 100.0 if entry > 0 and size > 0 else 0.0

        # Observation-only profit-retention shadow. This never changes live
        # protection or sends an order. It records the first sampled point at
        # which tighter 0.40pp / 0.30pp giveback rules, or a 50%-of-peak floor,
        # would have asked to exit. The peak-floor test arms after +0.50%.
        rec = retention.get(coin, {}) if isinstance(retention.get(coin), dict) else {}
        same_position = (
            rec.get("side") == side
            and abs(float(rec.get("entry_px", 0.0) or 0.0) - entry) <= max(1e-12, entry * 1e-8)
        )
        if not same_position:
            rec = {
                "side": side,
                "entry_px": entry,
                "started_at": dt.datetime.now(dt.UTC).isoformat(),
                "peak_return_pct": ret,
                "tests": {},
            }
        peak_ret = max(float(rec.get("peak_return_pct", ret) or ret), ret)
        rec["peak_return_pct"] = peak_ret
        rec["current_return_pct"] = ret
        rec["updated_at"] = dt.datetime.now(dt.UTC).isoformat()
        rec["observation_only"] = True
        rec["accounting_note"] = (
            "Sampled hypothetical return only; no order is sent and fees/funding "
            "are not estimated here."
        )
        tests = rec.setdefault("tests", {})
        candidates = {
            "giveback_0_40pp": peak_ret >= 0.40 and (peak_ret - ret) >= 0.40,
            "giveback_0_30pp": peak_ret >= 0.40 and (peak_ret - ret) >= 0.30,
            "keep_50pct_of_peak": peak_ret >= 0.50 and ret <= (peak_ret * 0.50),
        }
        for test_name, triggered in candidates.items():
            item = tests.setdefault(test_name, {"triggered": False})
            if triggered and not item.get("triggered"):
                item.update({
                    "triggered": True,
                    "triggered_at": dt.datetime.now(dt.UTC).isoformat(),
                    "sampled_exit_return_pct": ret,
                    "peak_return_pct_at_trigger": peak_ret,
                })
        retention[coin] = rec

        # Observation-only downside-risk shadow for adverse entries, especially
        # longs that struggle during falling markets. It never sends an order
        # or changes a live stop.
        loss_shadow = state.setdefault("aggressive_loss_protection_shadow", {})
        loss_rec = loss_shadow.get(coin, {}) if isinstance(loss_shadow.get(coin), dict) else {}
        loss_same_position = (
            loss_rec.get("side") == side
            and abs(float(loss_rec.get("entry_px", 0.0) or 0.0) - entry) <= max(1e-12, entry * 1e-8)
        )
        if not loss_same_position:
            loss_rec = {
                "side": side,
                "entry_px": entry,
                "started_at": dt.datetime.now(dt.UTC).isoformat(),
                "worst_return_pct": ret,
                "tests": {},
            }
        loss_rec["worst_return_pct"] = min(float(loss_rec.get("worst_return_pct", ret) or ret), ret)
        loss_rec["current_return_pct"] = ret
        loss_rec["updated_at"] = dt.datetime.now(dt.UTC).isoformat()
        loss_rec["observation_only"] = True
        loss_rec["research_focus"] = "downtrend / adverse-entry loss containment"
        loss_rec["accounting_note"] = (
            "Sampled hypothetical return only; no order is sent and fees/funding "
            "are not estimated here."
        )
        loss_tests = loss_rec.setdefault("tests", {})
        for test_name, threshold in {
            "loss_cap_0_75pct": -0.75,
            "loss_cap_1_00pct": -1.00,
            "loss_cap_1_50pct": -1.50,
        }.items():
            item = loss_tests.setdefault(test_name, {"triggered": False, "threshold_pct": threshold})
            if ret <= threshold and not item.get("triggered"):
                item.update({
                    "triggered": True,
                    "triggered_at": dt.datetime.now(dt.UTC).isoformat(),
                    "sampled_exit_return_pct": ret,
                })
        loss_shadow[coin] = loss_rec

        # Observation-only live thesis monitor. Research only: no orders.
        thesis_shadow = state.setdefault("aggressive_live_thesis_shadow", {})
        thesis_rec = thesis_shadow.get(coin, {}) if isinstance(thesis_shadow.get(coin), dict) else {}
        thesis_same_position = (
            thesis_rec.get("side") == side
            and abs(float(thesis_rec.get("entry_px", 0.0) or 0.0) - entry) <= max(1e-12, entry * 1e-8)
        )
        if not thesis_same_position:
            thesis_rec = {"side": side, "entry_px": entry, "started_at": dt.datetime.now(dt.UTC).isoformat(), "first_adverse_turn": None}
        close_s = df["Close"].astype(float)
        ema_fast = close_s.ewm(span=8, adjust=False).mean()
        ema_slow = close_s.ewm(span=21, adjust=False).mean()
        fast_now = float(ema_fast.iloc[-1])
        slow_now = float(ema_slow.iloc[-1])
        fast_prev = float(ema_fast.iloc[-2])
        momentum = current - float(close_s.iloc[-2])
        if side == "long":
            trend_against = fast_now < slow_now
            momentum_against = momentum < 0 and fast_now < fast_prev
        else:
            trend_against = fast_now > slow_now
            momentum_against = momentum > 0 and fast_now > fast_prev
        adverse_score = int(trend_against) + int(momentum_against)
        adverse_turn = adverse_score >= 2
        now_iso = dt.datetime.now(dt.UTC).isoformat()
        thesis_rec.update({"current_return_pct": ret, "ema8": fast_now, "ema21": slow_now, "trend_against_trade": bool(trend_against), "momentum_against_trade": bool(momentum_against), "adverse_score": adverse_score, "adverse_turn": bool(adverse_turn), "updated_at": now_iso, "observation_only": True, "rule": "flag when EMA8/EMA21 trend and latest 30m momentum both turn against the open trade", "accounting_note": "Research signal only; no live exit/order is sent."})
        if adverse_turn and thesis_rec.get("first_adverse_turn") is None:
            thesis_rec["first_adverse_turn"] = {"timestamp": now_iso, "sampled_return_pct": ret}
        thesis_shadow[coin] = thesis_rec

        shadow[coin] = {
            "side": side,
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
    state["aggressive_profit_retention_shadow"] = retention
    save_state(state)
    print("Aggressive exit shadow suite done")


if __name__ == "__main__":
    main()
