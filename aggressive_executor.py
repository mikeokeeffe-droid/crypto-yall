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
        raise RuntimeError(
            "Cannot load aggressive state: GIST_TOKEN or AGGRESSIVE_GIST_ID is missing"
        )

    try:
        resp = requests.get(
            f"https://api.github.com/gists/{gist_id}",
            headers={"Authorization": f"token {gist_token}"},
            timeout=15,
        )
    except requests.RequestException as e:
        raise RuntimeError(
            f"Failed to load aggressive state from Gist: {e}"
        ) from e

    if not resp.ok:
        raise RuntimeError(
            f"Failed to load aggressive state from Gist: "
            f"HTTP {resp.status_code} {resp.text}"
        )

    try:
        files = resp.json().get("files", {})

        if STATE_FILENAME not in files:
            raise KeyError(
                f"{STATE_FILENAME} not found in Aggressive Gist"
            )

        state = json.loads(
            files[STATE_FILENAME]["content"]
        )

        if not isinstance(state, dict):
            raise TypeError("Aggressive state is not a JSON object")

    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise RuntimeError(
            f"Aggressive Gist state is invalid: {e}"
        ) from e

    print("Aggressive state loaded successfully")
    return state

def save_state(state: dict):
    gist_token = os.environ.get("GIST_TOKEN")
    gist_id = os.environ.get("AGGRESSIVE_GIST_ID")
    if not gist_token or not gist_id:
        raise RuntimeError(
            "Cannot save aggressive state: GIST_TOKEN or AGGRESSIVE_GIST_ID is missing"
        )

    resp = requests.patch(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"token {gist_token}"},
        json={"files": {STATE_FILENAME: {"content": json.dumps(state, indent=2)}}},
        timeout=15,
    )

    if not resp.ok:
        raise RuntimeError(
            f"Failed to save aggressive state to Gist: "
            f"HTTP {resp.status_code} {resp.text}"
        )

    print("Aggressive state saved successfully")



def update_peak_tracking(state: dict, positions: dict, owned_coins: set[str]) -> None:
    """
    Track the best unrealized profit seen for each currently owned position.

    Observation-only: this does not open, close, resize, or otherwise
    change any trade.
    """
    peak_pnl = {
        str(k): float(v)
        for k, v in (state.get("peak_pnl", {}) or {}).items()
    }
    peak_return_pct = {
        str(k): float(v)
        for k, v in (state.get("peak_return_pct", {}) or {}).items()
    }

    for coin in list(peak_pnl):
        if coin not in owned_coins:
            peak_pnl.pop(coin, None)
    for coin in list(peak_return_pct):
        if coin not in owned_coins:
            peak_return_pct.pop(coin, None)

    for coin in owned_coins:
        pos = positions.get(coin)
        if not pos:
            continue

        current_pnl = float(pos.get("unrealized_pnl", 0.0) or 0.0)
        peak_pnl[coin] = max(
            float(peak_pnl.get(coin, 0.0) or 0.0),
            current_pnl,
        )

        entry_px = float(pos.get("entry_px", 0.0) or 0.0)
        size = abs(float(pos.get("size", 0.0) or 0.0))
        if entry_px > 0 and size > 0:
            current_return_pct = current_pnl / (entry_px * size) * 100.0
            peak_return_pct[coin] = max(
                float(peak_return_pct.get(coin, 0.0) or 0.0),
                current_return_pct,
            )

    state["peak_pnl"] = peak_pnl
    state["peak_return_pct"] = peak_return_pct


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

        # Pyramid only into a position that is currently profitable.
        # This prevents averaging up into a trade that has already turned
        # into a loser.
        current_unrealized = float(
            remaining[hl_coin].get("unrealized_pnl", 0.0) or 0.0
        )
        if current_unrealized <= 0:
            print(
                f"Skipping pyramid for {hl_coin}: "
                f"position is not profitable "
                f"(uPnL ${current_unrealized:.4f})"
            )
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

    slots = max(0, max_positions - len(remaining))

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


def check_daily_drawdown(
    state: dict,
    info,
    address: str,
    capital: float,
    threshold: float,
) -> tuple[bool, dict]:
    """
    Check this bot's daily P&L against its own allocated capital.

    Uses only positions listed in owned_coins plus realized P&L tracked by this
    bot. This avoids false halts caused by deposits, withdrawals, or the other
    bots sharing the same Hyperliquid account.
    """
    today = dt.date.today().isoformat()
    open_positions = get_open_positions(info, address)
    owned_coins = set(state.get("owned_coins", []))

    realized_total = float(
        state.get("realized_pnl_total", 0.0) or 0.0
    )
    unrealized = sum(
        float(open_positions[coin].get("unrealized_pnl", 0.0) or 0.0)
        for coin in owned_coins
        if coin in open_positions
    )

    # Continuous bot-only P&L marker. When a position closes through this bot,
    # its unrealized P&L is replaced by realized_pnl_total so the marker does
    # not jump merely because the trade moved from open to closed.
    pnl_marker = realized_total + unrealized
    key = f"bot_day_start_pnl_{today}"
    start_marker = state.get(key)

    update = {
        "last_bot_pnl_marker": pnl_marker,
        "last_bot_unrealized_pnl": unrealized,
        "last_bot_realized_pnl_total": realized_total,
    }

    if start_marker is None:
        update[key] = pnl_marker
        update["last_bot_daily_pnl"] = 0.0
        update["last_bot_dd_pct"] = 0.0
        return False, update

    daily_pnl = pnl_marker - float(start_marker)
    dd_pct = (
        daily_pnl / capital * 100
        if capital > 0
        else 0.0
    )

    update["last_bot_daily_pnl"] = daily_pnl
    update["last_bot_dd_pct"] = dd_pct

    if dd_pct <= -threshold:
        update["halted_today"] = today
        update["halt_reason"] = (
            f"Aggressive bot DD {dd_pct:.2f}% exceeded {-threshold}% "
            f"(daily P&L ${daily_pnl:.2f} on ${capital:.2f} capital)"
        )
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
    capital = float(os.environ.get("AGGRESSIVE_CAPITAL", "3000"))
    threshold = float(os.environ.get("AGGRESSIVE_DD_PCT", "3"))
    halted, state_update = check_daily_drawdown(
        state,
        info,
        address,
        capital,
        threshold,
    )
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

    # Observation-only peak-profit tracking for currently owned positions.
    update_peak_tracking(state, managed_positions, owned_coins)

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
                previous = managed_positions.get(coin)

                if previous is not None:
                    entry_px = float(previous["entry_px"])
                    fill_px = float(result.get("fill_price", entry_px))
                    fill_size = abs(float(
                        result.get("fill_size", previous["size"])
                    ))

                    if float(previous["size"]) > 0:
                        realized_pnl = (fill_px - entry_px) * fill_size
                    else:
                        realized_pnl = (entry_px - fill_px) * fill_size

                    result["realized_pnl"] = realized_pnl

                    peak_pnl = float(
                        (state.get("peak_pnl", {}) or {}).get(coin, 0.0) or 0.0
                    )
                    peak_return_pct = float(
                        (state.get("peak_return_pct", {}) or {}).get(coin, 0.0) or 0.0
                    )
                    entry_notional = entry_px * fill_size
                    realized_return_pct = (
                        realized_pnl / entry_notional * 100.0
                        if entry_notional > 0
                        else 0.0
                    )

                    result["peak_unrealized_pnl"] = peak_pnl
                    result["peak_return_pct"] = peak_return_pct
                    result["realized_return_pct"] = realized_return_pct
                    result["profit_giveback"] = peak_pnl - realized_pnl

                    state["realized_pnl_total"] = (
                        float(state.get("realized_pnl_total", 0.0) or 0.0)
                        + realized_pnl
                    )

                    print(
                        f"    Realized P&L: ${realized_pnl:.4f} "
                        f"| peak: ${peak_pnl:.4f} "
                        f"| giveback: ${result['profit_giveback']:.4f} "
                        f"| bot total: ${state['realized_pnl_total']:.4f}"
                    )

                owned_coins.discard(coin)
                pyramid_state.pop(coin, None)
                state.setdefault("peak_pnl", {}).pop(coin, None)
                state.setdefault("peak_return_pct", {}).pop(coin, None)
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

    # Refresh peaks after any fills so newly opened positions get tracked too.
    update_peak_tracking(state, state["open_positions"], owned_coins)

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