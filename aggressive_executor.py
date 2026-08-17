"""
aggressive_executor.py — 30-min trade executor with pyramiding.

Higher trade frequency than the standard intraday bot. Tighter stops,
tighter drawdown halt, more max positions. Operates on a completely
separate capital pool and state Gist.

Required environment variables:
    HL_PRIVATE_KEY / HL_ACCOUNT_ADDRESS / HL_TESTNET
    GIST_TOKEN / AGGRESSIVE_GIST_ID    (separate from daily & intraday Gists)
    AGGRESSIVE_CAPITAL                  (capital pool, e.g. 3000)
    AGGRESSIVE_MAX_POSITIONS            (defaults to 4)
    AGGRESSIVE_DD_PCT                   (defaults to 3 — tighter than others)
    AGGRESSIVE_KILL_SWITCH              ("OFF" halts aggressive only)
    GMAIL_USER / GMAIL_APP_PASSWORD / NOTIFY_EMAILS
    TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
"""

import json
import os
import sys
import datetime as dt

import requests

from intraday_data_loader import fetch_all_intraday, HL_SYMBOL_MAP
from aggressive_strategy import generate_aggressive_signals, classify_aggressive_signal
from hyperliquid_executor import (
    ASSETS,
    get_client,
    get_account_equity,
    get_open_positions,
    get_mid_price,
    get_size_decimals,
    round_size,
    _parse_response,
    _send_email,
    _send_telegram,
)
from backtester import get_asset_profile


STATE_FILENAME = "aggressive_state.json"
POSITION_SIZE_PCT = 0.015  # 1.5% per trade — higher than standard intraday
PYRAMID_SIZE_PCT = 0.005   # 0.5% extra per pyramid add (max 2 adds)
TESTNET_MIN_ORDER_NOTIONAL = 12.0  # buffer above Hyperliquid $10 minimum


# ── State persistence (separate Gist) ───────────────────────────────────────

def load_state() -> dict:
    gist_token = os.environ.get("GIST_TOKEN")
    gist_id = os.environ.get("AGGRESSIVE_GIST_ID")
    if not gist_token or not gist_id:
        return {}
    resp = requests.get(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"token {gist_token}"},
        timeout=15,
    )
    if resp.status_code != 200:
        return {}
    files = resp.json().get("files", {})
    if STATE_FILENAME not in files:
        return {}
    try:
        return json.loads(files[STATE_FILENAME]["content"])
    except Exception:
        return {}


def save_state(state: dict):
    gist_token = os.environ.get("GIST_TOKEN")
    gist_id = os.environ.get("AGGRESSIVE_GIST_ID")
    if not gist_token or not gist_id:
        return
    requests.patch(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"token {gist_token}"},
        json={"files": {STATE_FILENAME: {"content": json.dumps(state, indent=2)}}},
        timeout=15,
    )


# ── Signal computation ─────────────────────────────────────────────────────

def compute_aggressive_signals() -> dict:
    """Fetch 30-min candles and compute aggressive signals per asset."""
    all_data = fetch_all_intraday(list(ASSETS.keys()), interval="30m", lookback_hours=1000)
    current = {}

    for ticker in ASSETS:
        try:
            df = all_data.get(ticker)
            if df is None or df.empty or len(df) < 50:
                continue

            profile = get_asset_profile(ticker)
            sig = generate_aggressive_signals(df, allow_short=profile["allow_short"])

            last = int(sig["Signal"].iloc[-1])
            prev = int(sig["Signal"].iloc[-2]) if len(sig) >= 2 else last
            action = classify_aggressive_signal(last, prev)
            price = float(df["Close"].iloc[-1])
            osc = float(sig["TwoPole_Osc"].iloc[-1]) if "TwoPole_Osc" in sig.columns else 0.0
            pyramid = int(sig["Pyramid"].iloc[-1]) if "Pyramid" in sig.columns else 0
            prev_pyramid = int(sig["Pyramid"].iloc[-2]) if len(sig) >= 2 and "Pyramid" in sig.columns else pyramid

            current[ticker] = {
                "signal": last,
                "action": action,
                "price": price,
                "osc": osc,
                "pyramid": pyramid,
                "pyramid_added": pyramid > prev_pyramid,  # fresh pyramid this bar
            }
        except Exception as e:
            print(f"Error on {ticker}: {e}")

    return current


# ── Trade decisions ─────────────────────────────────────────────────────────

def decide_trades(signals: dict, open_positions: dict, max_positions: int,
                  pyramid_state: dict) -> list[dict]:
    """Decide trades, including pyramid adds on existing winners."""
    trades = []

    # Close out positions that should exit
    for ticker, info in signals.items():
        hl_coin = HL_SYMBOL_MAP[ticker]
        pos = open_positions.get(hl_coin)
        if pos is None:
            continue
        is_long = pos["size"] > 0
        is_short = pos["size"] < 0

        action = info["action"]
        if (action == "sell_exit" and is_long) or \
           (action == "cover_short" and is_short) or \
           (action == "buy" and is_short) or \
           (action == "enter_short" and is_long):
            trades.append({
                "ticker": ticker, "hl_coin": hl_coin,
                "action": "close",
                "side": "long" if is_long else "short",
                "reason": f"{action} signal",
            })

    closes = {t["hl_coin"] for t in trades if t["action"] == "close"}
    remaining = {c: p for c, p in open_positions.items() if c not in closes}

    # Pyramid adds on existing winners — these don't count toward max_positions
    for ticker, info in signals.items():
        hl_coin = HL_SYMBOL_MAP[ticker]
        if hl_coin not in remaining:
            continue
        if not info.get("pyramid_added"):
            continue
        # Limit pyramid count
        current_pyramid = pyramid_state.get(hl_coin, 0)
        if current_pyramid >= 2:
            continue
        side = "long" if remaining[hl_coin]["size"] > 0 else "short"
        trades.append({
            "ticker": ticker, "hl_coin": hl_coin,
            "action": f"pyramid_{side}",
            "side": side,
            "reason": f"pyramid add #{current_pyramid + 1} (osc re-entry)",
        })

    slots = max_positions - len(remaining)

    # Open new positions, prioritized by oscillator magnitude
    candidates = []
    for ticker, info in signals.items():
        hl_coin = HL_SYMBOL_MAP[ticker]
        if hl_coin in remaining:
            continue
        action = info["action"]
        if action in ("buy", "hold_long"):
            reason = "buy signal" if action == "buy" else "sync to hold_long"
            candidates.append({
                "ticker": ticker, "hl_coin": hl_coin,
                "action": "open_long", "side": "long",
                "reason": reason,
                "priority": abs(info["osc"]),
            })
        elif action in ("enter_short", "hold_short"):
            reason = "enter_short signal" if action == "enter_short" else "sync to hold_short"
            candidates.append({
                "ticker": ticker, "hl_coin": hl_coin,
                "action": "open_short", "side": "short",
                "reason": reason,
                "priority": abs(info["osc"]),
            })

    candidates.sort(key=lambda c: c["priority"], reverse=True)
    trades.extend(candidates[:slots])
    return trades


def execute_trade(info, exchange, trade: dict, capital: float, leverage: float) -> dict:
    coin = trade["hl_coin"]
    if trade["action"] == "close":
        resp = exchange.market_close(coin)
        return _parse_response(trade, resp, info, coin)

    mid = get_mid_price(info, coin)
    # Pyramid adds use smaller size
    size_pct = PYRAMID_SIZE_PCT if trade["action"].startswith("pyramid_") else POSITION_SIZE_PCT
    requested_notional = capital * size_pct * leverage
    test_notional = float(os.environ.get("AGGRESSIVE_TEST_NOTIONAL", "0") or 0)

    # On testnet only, raise tiny test orders above Hyperliquid's $10 minimum.
    # On mainnet, never silently increase real-money risk: skip undersized orders.
    is_testnet = os.environ.get("HL_TESTNET", "true").lower() == "true"

    # Optional controlled mainnet test size for NEW positions only.
    # Pyramid adds keep their normal smaller strategy sizing.
    if (not is_testnet) and test_notional > 0 and not trade["action"].startswith("pyramid_"):
        requested_notional = test_notional
    if is_testnet and requested_notional < TESTNET_MIN_ORDER_NOTIONAL:
        notional = TESTNET_MIN_ORDER_NOTIONAL
    elif (not is_testnet) and requested_notional < 10.0:
        return {
            **trade,
            "status": "skipped",
            "reason": (
                f"Calculated order ${requested_notional:.2f} is below "
                "Hyperliquid's $10 minimum"
            ),
        }
    else:
        notional = requested_notional

    raw_size = notional / mid
    sz_decimals = get_size_decimals(info, coin)
    size = round_size(raw_size, sz_decimals)
    if size <= 0:
        return {**trade, "status": "skipped", "reason": "Size rounded to zero"}

    try:
        exchange.update_leverage(int(leverage), coin, True)
    except Exception as e:
        print(f"Leverage warning for {coin}: {e}")

    is_buy = trade["action"] in ("open_long", "pyramid_long")
    resp = exchange.market_open(coin, is_buy, size)
    return _parse_response(trade, resp, info, coin)


# ── Guardrails ──────────────────────────────────────────────────────────────

def kill_switch_off() -> bool:
    return os.environ.get("AGGRESSIVE_KILL_SWITCH", "ON").upper() == "OFF"


def check_daily_drawdown(state: dict, equity: float, threshold: float) -> tuple[bool, dict]:
    today = dt.date.today().isoformat()
    key = f"day_start_{today}"
    start = state.get(key)
    update = {}
    if start is None:
        update[key] = equity
        return False, update
    dd = (equity - start) / start * 100 if start > 0 else 0
    if dd <= -threshold:
        update["halted_today"] = today
        update["halt_reason"] = f"Aggressive DD {dd:.2f}% exceeded {-threshold}%"
        return True, update
    return False, update


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    print(f"Aggressive executor started at {dt.datetime.now(dt.UTC).isoformat()}")

    if kill_switch_off():
        print("Aggressive KILL_SWITCH is OFF — halting")
        sys.exit(0)

    try:
        info, exchange, address = get_client()
    except Exception as e:
        print(f"Client init failed: {e}")
        _send_email([], f"AGGRESSIVE CLIENT INIT FAILED: {e}")
        sys.exit(1)

    state = load_state()
    equity = get_account_equity(info, address)
    threshold = float(os.environ.get("AGGRESSIVE_DD_PCT", "3"))
    halted, state_update = check_daily_drawdown(state, equity, threshold)
    state.update(state_update)

    if halted:
        msg = f"Aggressive halted: {state_update.get('halt_reason')}"
        print(msg)
        _send_email([], msg)
        save_state(state)
        sys.exit(0)

    today = dt.date.today().isoformat()
    if state.get("halted_today") == today:
        print(f"Already halted today: {state.get('halt_reason')}")
        sys.exit(0)

    signals = compute_aggressive_signals()
    open_positions = get_open_positions(info, address)
    capital = float(os.environ.get("AGGRESSIVE_CAPITAL", "3000"))
    max_positions = int(os.environ.get("AGGRESSIVE_MAX_POSITIONS", "4"))

    # Filter assets to those listed on this Hyperliquid environment
    available = set(info.all_mids().keys())
    signals = {t: s for t, s in signals.items() if HL_SYMBOL_MAP[t] in available}
    skipped = [t for t in ASSETS if t not in signals]
    if skipped:
        print(f"Skipping unavailable assets on this env: {skipped}")

    # Ownership tracking with stale-position reconciliation
    owned_coins = set(state.get("owned_coins", []))
    stale_owned = owned_coins - set(open_positions.keys())
    if stale_owned:
        print(f"Dropping stale owned coins (no position on exchange): {stale_owned}")
        owned_coins -= stale_owned

    managed_positions = {c: p for c, p in open_positions.items() if c in owned_coins}

    # Per-coin pyramid state (persisted across runs)
    pyramid_state = state.get("pyramid_state", {})

    trades = decide_trades(signals, managed_positions, max_positions, pyramid_state)

    # Cross-bot position lock:
    # Never open/pyramid a coin already present on the shared Hyperliquid
    # account unless this aggressive bot owns it.
    foreign_coins = set(open_positions.keys()) - owned_coins
    if foreign_coins:
        print(f"Cross-bot lock: coins owned elsewhere: {sorted(foreign_coins)}")
        trades = [
            t for t in trades
            if t["action"] == "close" or t["hl_coin"] not in foreign_coins
        ]

    print(f"Decided on {len(trades)} aggressive trade(s) (own {len(owned_coins)} position(s))")

    results = []
    for trade in trades:
        # Aggressive leverage: 4x for large cap (capped at 3x by HL), 1.5x for mid cap
        profile = get_asset_profile(trade["ticker"])
        leverage = min(4.0, profile["max_bull_leverage"] * 1.33)  # bumped from standard
        result = execute_trade(info, exchange, trade, capital, leverage)
        results.append(result)
        print(f"  {result['ticker']} {result['action']}: {result.get('status')}")

        if result.get("status") == "filled":
            coin = result["hl_coin"]
            if result["action"] == "close":
                owned_coins.discard(coin)
                pyramid_state.pop(coin, None)
            elif result["action"].startswith("pyramid_"):
                pyramid_state[coin] = pyramid_state.get(coin, 0) + 1
            else:
                owned_coins.add(coin)
                pyramid_state[coin] = 0

    history = state.get("history", [])
    for r in results:
        history.append({
            "timestamp": dt.datetime.now(dt.UTC).isoformat(),
            **{k: v for k, v in r.items() if k != "raw"},
        })
    state["history"] = history[-500:]
    state["last_equity"] = equity
    state["last_run"] = dt.datetime.now(dt.UTC).isoformat()
    state["owned_coins"] = sorted(owned_coins)
    state["pyramid_state"] = pyramid_state
    latest = get_open_positions(info, address)
    state["open_positions"] = {c: p for c, p in latest.items() if c in owned_coins}
    state["last_signals"] = signals
    save_state(state)

    filled_count = sum(1 for r in results if r.get("status") == "filled")
    error_count = sum(1 for r in results if r.get("status") == "error")
    skipped_count = sum(1 for r in results if r.get("status") == "skipped")
    summary = (
        f"{filled_count} aggressive filled"
        f" | {error_count} error(s)"
        f" | {skipped_count} skipped"
        f" | Equity: ${equity:,.2f}"
    )
    if results:
        _send_email(results, summary)
        _send_telegram(results, summary)
    print("Done")


if __name__ == "__main__":
    main()