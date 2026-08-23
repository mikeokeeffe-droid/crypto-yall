"""
intraday_executor.py — Hourly trade executor using the 1h 2-pole oscillator.

Reuses the Hyperliquid client code from hyperliquid_executor but runs on
intraday candles from Hyperliquid's own candle endpoint. Completely
independent state and capital from the daily bot.

Required environment variables (shared with daily bot):
    HL_PRIVATE_KEY / HL_ACCOUNT_ADDRESS / HL_TESTNET
    GIST_TOKEN / INTRADAY_GIST_ID    (separate from daily trading Gist)
    INTRADAY_CAPITAL                  (capital pool dedicated to intraday)
    INTRADAY_MAX_POSITIONS            (defaults to 2)
    INTRADAY_DD_PCT                   (daily drawdown cutoff, e.g. 5)
    INTRADAY_KILL_SWITCH              ("OFF" halts intraday only)
    GMAIL_USER / GMAIL_APP_PASSWORD / NOTIFY_EMAILS
    TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
"""

import json
import os
import sys
import datetime as dt

import requests

from intraday_data_loader import fetch_all_intraday, HL_SYMBOL_MAP
from intraday_strategy import generate_intraday_signals, classify_intraday_signal
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


STATE_FILENAME = "intraday_state.json"
POSITION_SIZE_PCT = 0.01
TESTNET_MIN_ORDER_NOTIONAL = 12.0
MAINNET_MIN_ORDER_NOTIONAL = 10.0


# ── State persistence (separate Gist from daily bot) ────────────────────────

def load_state() -> dict:
    gist_token = os.environ.get("GIST_TOKEN")
    gist_id = os.environ.get("INTRADAY_GIST_ID")

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
    gist_id = os.environ.get("INTRADAY_GIST_ID")

    if not gist_token or not gist_id:
        raise RuntimeError(
            "Cannot save intraday state: GIST_TOKEN or INTRADAY_GIST_ID is missing"
        )

    resp = requests.patch(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"token {gist_token}"},
        json={"files": {STATE_FILENAME: {"content": json.dumps(state, indent=2)}}},
        timeout=15,
    )

    if not resp.ok:
        raise RuntimeError(
            f"Failed to save intraday state to Gist: "
            f"HTTP {resp.status_code} {resp.text}"
        )

    print("Intraday state saved successfully")



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

def compute_intraday_signals() -> dict:
    """Fetch 1h candles and compute signals per asset."""
    all_data = fetch_all_intraday(
        list(ASSETS.keys()),
        interval="1h",
        lookback_hours=1000,
    )
    current = {}

    for ticker in ASSETS:
        try:
            df = all_data.get(ticker)

            if df is None or df.empty or len(df) < 50:
                continue

            profile = get_asset_profile(ticker)
            sig = generate_intraday_signals(
                df,
                allow_short=profile["allow_short"],
            )

            last = int(sig["Signal"].iloc[-1])
            prev = int(sig["Signal"].iloc[-2]) if len(sig) >= 2 else last
            action = classify_intraday_signal(last, prev)
            price = float(df["Close"].iloc[-1])
            osc = (
                float(sig["TwoPole_Osc"].iloc[-1])
                if "TwoPole_Osc" in sig.columns
                else 0.0
            )

            current[ticker] = {
                "signal": last,
                "action": action,
                "price": price,
                "osc": osc,
            }

        except Exception as e:
            print(f"Error on {ticker}: {e}")

    return current


# ── Trade decisions ────────────────────────────────────────────────────────

def decide_trades(
    signals: dict,
    open_positions: dict,
    max_positions: int,
) -> list[dict]:
    """Decide trades given new signals vs current HL positions."""
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

        if (
            (action == "sell_exit" and is_long)
            or (action == "cover_short" and is_short)
            or (action == "buy" and is_short)
            or (action == "enter_short" and is_long)
        ):
            trades.append({
                "ticker": ticker,
                "hl_coin": hl_coin,
                "action": "close",
                "side": "long" if is_long else "short",
                "reason": f"{action} signal",
            })

    closes = {
        t["hl_coin"]
        for t in trades
        if t["action"] == "close"
    }

    remaining = {
        c: p
        for c, p in open_positions.items()
        if c not in closes
    }

    slots = max_positions - len(remaining)

    # Open new positions, prioritized by oscillator magnitude
    candidates = []

    for ticker, info in signals.items():
        hl_coin = HL_SYMBOL_MAP[ticker]

        if hl_coin in remaining:
            continue

        action = info["action"]

        # Keep original project behavior:
        # open on fresh entry OR sync when strategy says it should be holding.
        if action in ("buy", "hold_long"):
            reason = (
                "buy signal"
                if action == "buy"
                else "sync to hold_long"
            )

            candidates.append({
                "ticker": ticker,
                "hl_coin": hl_coin,
                "action": "open_long",
                "side": "long",
                "reason": reason,
                "priority": abs(info["osc"]),
            })

        elif action in ("enter_short", "hold_short"):
            reason = (
                "enter_short signal"
                if action == "enter_short"
                else "sync to hold_short"
            )

            candidates.append({
                "ticker": ticker,
                "hl_coin": hl_coin,
                "action": "open_short",
                "side": "short",
                "reason": reason,
                "priority": abs(info["osc"]),
            })

    candidates.sort(key=lambda c: c["priority"], reverse=True)
    trades.extend(candidates[:slots])

    return trades


def execute_trade(
    info,
    exchange,
    trade: dict,
    capital: float,
    leverage: float,
) -> dict:
    coin = trade["hl_coin"]

    if trade["action"] == "close":
        resp = exchange.market_close(coin)
        return _parse_response(trade, resp, info, coin)

    mid = get_mid_price(info, coin)
    calculated_notional = capital * POSITION_SIZE_PCT * leverage
    test_notional = float(os.environ.get("INTRADAY_TEST_NOTIONAL", "0") or 0)
    is_testnet = os.environ.get("HL_TESTNET", "true").lower() == "true"

    if is_testnet:
        # Testnet: use a small buffer above Hyperliquid's $10 minimum so
        # low-capital validation trades can actually be accepted.
        notional = max(
            calculated_notional,
            TESTNET_MIN_ORDER_NOTIONAL,
        )
    else:
        if test_notional > 0:
            calculated_notional = test_notional
        # Mainnet: never silently increase real-money risk above the
        # strategy's calculated position size.
        if calculated_notional < MAINNET_MIN_ORDER_NOTIONAL:
            return {
                **trade,
                "status": "skipped",
                "reason": (
                    f"Calculated order ${calculated_notional:.2f} is below "
                    f"the ${MAINNET_MIN_ORDER_NOTIONAL:.2f} minimum"
                ),
            }

        notional = calculated_notional

    # Do not let the testnet minimum exceed the capital pool multiplied by
    # the strategy leverage.
    max_notional = capital * max(leverage, 1.0)

    if notional > max_notional:
        return {
            **trade,
            "status": "skipped",
            "reason": (
                f"Capital pool too small for ${notional:.2f} minimum order"
            ),
        }

    raw_size = notional / mid
    sz_decimals = get_size_decimals(info, coin)
    size = round_size(raw_size, sz_decimals)

    if size <= 0:
        return {
            **trade,
            "status": "skipped",
            "reason": "Size rounded to zero",
        }

    try:
        exchange.update_leverage(int(leverage), coin, True)
    except Exception as e:
        print(f"Leverage warning for {coin}: {e}")

    is_buy = trade["action"] == "open_long"
    resp = exchange.market_open(coin, is_buy, size)

    return _parse_response(trade, resp, info, coin)


# ── Guardrails ──────────────────────────────────────────────────────────────

def kill_switch_off() -> bool:
    """Return True when intraday trading is halted."""
    return os.environ.get(
        "INTRADAY_KILL_SWITCH",
        "ON",
    ).upper() == "OFF"


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

    # A continuous bot-only P&L marker. When a position closes, its unrealized
    # P&L is replaced by realized_pnl_total, so the marker does not jump merely
    # because the trade moved from open to closed.
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
            f"Intraday bot DD {dd_pct:.2f}% exceeded {-threshold}% "
            f"(daily P&L ${daily_pnl:.2f} on ${capital:.2f} capital)"
        )
        return True, update

    return False, update


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    print(
        "Intraday executor started at "
        f"{dt.datetime.now(dt.UTC).isoformat()}"
    )

    if kill_switch_off():
        print("Intraday KILL_SWITCH is OFF — halting")
        sys.exit(0)

    try:
        info, exchange, address = get_client()
    except Exception as e:
        print(f"Client init failed: {e}")
        _send_email([], f"INTRADAY CLIENT INIT FAILED: {e}")
        sys.exit(1)

    state = load_state()
    equity = get_account_equity(info, address)
    capital = float(
        os.environ.get("INTRADAY_CAPITAL", "5000")
    )
    threshold = float(
        os.environ.get("INTRADAY_DD_PCT", "5")
    )

    halted, state_update = check_daily_drawdown(
        state,
        info,
        address,
        capital,
        threshold,
    )

    state.update(state_update)

    if halted:
        msg = (
            "Intraday halted: "
            f"{state_update.get('halt_reason')}"
        )
        print(msg)
        _send_email([], msg)
        save_state(state)
        sys.exit(0)

    today = dt.date.today().isoformat()

    if state.get("halted_today") == today:
        print(
            "Already halted today: "
            f"{state.get('halt_reason')}"
        )
        sys.exit(0)

    signals = compute_intraday_signals()
    open_positions = get_open_positions(info, address)
    max_positions = int(
        os.environ.get("INTRADAY_MAX_POSITIONS", "2")
    )

    # Filter out assets not listed on this Hyperliquid environment
    available = set(info.all_mids().keys())

    signals = {
        t: s
        for t, s in signals.items()
        if HL_SYMBOL_MAP[t] in available
    }

    skipped_assets = [
        t
        for t in ASSETS
        if t not in signals
    ]

    if skipped_assets:
        print(
            "Skipping unavailable assets on this env: "
            f"{skipped_assets}"
        )

    # Ownership tracking: only manage positions this bot opened
    owned_coins = set(
        state.get("owned_coins", [])
    )

    stale_owned = (
        owned_coins
        - set(open_positions.keys())
    )

    if stale_owned:
        print(
            "Dropping stale owned coins "
            f"(no position on exchange): {stale_owned}"
        )
        owned_coins -= stale_owned

    managed_positions = {
        c: p
        for c, p in open_positions.items()
        if c in owned_coins
    }

    # Observation-only peak-profit tracking for currently owned positions.
    update_peak_tracking(state, managed_positions, owned_coins)

    trades = decide_trades(
        signals,
        managed_positions,
        max_positions,
    )

    # Cross-bot position lock:
    # The three bots share one Hyperliquid account but keep separate state.
    # Block this bot from opening a coin that is already present on the
    # exchange unless this bot owns it.
    foreign_coins = set(open_positions.keys()) - owned_coins
    if foreign_coins:
        print(
            "Cross-bot lock: coins owned elsewhere: "
            f"{sorted(foreign_coins)}"
        )
        trades = [
            t for t in trades
            if t["action"] == "close"
            or t["hl_coin"] not in foreign_coins
        ]

    print(
        f"Decided on {len(trades)} intraday trade(s) "
        f"(own {len(owned_coins)} position(s))"
    )

    results = []

    for trade in trades:
        leverage = 2.0

        result = execute_trade(
            info,
            exchange,
            trade,
            capital,
            leverage,
        )

        results.append(result)

        print(
            f"  {result['ticker']} "
            f"{result['action']}: "
            f"{result.get('status')}"
        )

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
                        f"| bot total: "
                        f"${state['realized_pnl_total']:.4f}"
                    )

                owned_coins.discard(coin)
                state.setdefault("peak_pnl", {}).pop(coin, None)
                state.setdefault("peak_return_pct", {}).pop(coin, None)
            else:
                owned_coins.add(coin)

    history = state.get("history", [])

    for r in results:
        history.append({
            "timestamp": dt.datetime.now(
                dt.UTC
            ).isoformat(),
            **{
                k: v
                for k, v in r.items()
                if k != "raw"
            },
        })

    state["history"] = history[-500:]
    state["last_equity"] = equity
    state["last_run"] = dt.datetime.now(
        dt.UTC
    ).isoformat()
    state["owned_coins"] = sorted(
        owned_coins
    )

    latest = get_open_positions(
        info,
        address,
    )

    state["open_positions"] = {
        c: p
        for c, p in latest.items()
        if c in owned_coins
    }

    # Refresh peaks after any fills so newly opened positions are tracked too.
    update_peak_tracking(state, state["open_positions"], owned_coins)

    state["last_signals"] = signals
    save_state(state)

    filled_count = sum(
        1
        for r in results
        if r.get("status") == "filled"
    )
    error_count = sum(
        1
        for r in results
        if r.get("status") == "error"
    )
    skipped_count = sum(
        1
        for r in results
        if r.get("status") == "skipped"
    )

    summary = (
        f"{filled_count} intraday filled"
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