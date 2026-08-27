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
    get_order_fill_totals,
    find_latest_open_history_record,
    get_position_funding,
    record_position_open_time,
    clear_position_open_time,
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
        raise RuntimeError(
            "Cannot load intraday state: GIST_TOKEN or INTRADAY_GIST_ID is missing"
        )

    try:
        resp = requests.get(
            f"https://api.github.com/gists/{gist_id}",
            headers={"Authorization": f"token {gist_token}"},
            timeout=15,
        )
    except requests.RequestException as e:
        raise RuntimeError(
            f"Failed to load intraday state from Gist: {e}"
        ) from e

    if not resp.ok:
        raise RuntimeError(
            f"Failed to load intraday state from Gist: "
            f"HTTP {resp.status_code} {resp.text}"
        )

    try:
        files = resp.json().get("files", {})

        if STATE_FILENAME not in files:
            raise KeyError(
                f"{STATE_FILENAME} not found in Intraday Gist"
            )

        state = json.loads(
            files[STATE_FILENAME]["content"]
        )

        if not isinstance(state, dict):
            raise TypeError("Intraday state is not a JSON object")

    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise RuntimeError(
            f"Intraday Gist state is invalid: {e}"
        ) from e

    print("Intraday state loaded successfully")
    return state

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


def calculate_rsi(closes, period: int = 14) -> float:
    """
    Calculate Wilder RSI for observation only.

    This value is never used by trade decisions. It is recorded alongside
    hourly flat observations so we can test whether RSI helps explain
    stay-flat vs subsequent exits.
    """
    values = [float(v) for v in closes if v is not None]
    if len(values) < period + 1:
        return 50.0

    gains = []
    losses = []
    for prev, curr in zip(values[:-1], values[1:]):
        change = curr - prev
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def update_flat_tracking(state: dict, signals: dict, owned_coins: set[str]) -> None:
    """
    Passively track how long an owned Intraday position remains on a flat signal.

    This is observation-only. It does not open, close, resize, rotate, or
    otherwise change any trade.

    flat_count counts distinct UTC hourly checks, so manually running the
    workflow more than once in the same hour will not inflate the count.
    """
    flat_count = {
        str(k): int(v)
        for k, v in (state.get("flat_count", {}) or {}).items()
    }
    flat_since = {
        str(k): str(v)
        for k, v in (state.get("flat_since", {}) or {}).items()
    }
    flat_last_counted_hour = {
        str(k): str(v)
        for k, v in (state.get("flat_last_counted_hour", {}) or {}).items()
    }
    flat_rsi_history = {
        str(k): list(v)
        for k, v in (state.get("flat_rsi_history", {}) or {}).items()
        if isinstance(v, list)
    }

    for store in (flat_count, flat_since, flat_last_counted_hour, flat_rsi_history):
        for coin in list(store):
            if coin not in owned_coins:
                store.pop(coin, None)

    signal_by_coin = {}
    for ticker, info in signals.items():
        coin = HL_SYMBOL_MAP.get(ticker)
        if coin:
            signal_by_coin[coin] = info

    now = dt.datetime.now(dt.UTC)
    now_iso = now.isoformat()
    hour_key = now.strftime("%Y-%m-%dT%H:00Z")

    for coin in owned_coins:
        info = signal_by_coin.get(coin)
        if info is None:
            continue

        action = info.get("action")

        if action == "flat":
            if coin not in flat_since:
                flat_since[coin] = now_iso

            if flat_last_counted_hour.get(coin) != hour_key:
                flat_count[coin] = int(flat_count.get(coin, 0) or 0) + 1
                flat_last_counted_hour[coin] = hour_key

                rsi_value = float(info.get("rsi", 50.0) or 50.0)
                flat_rsi_history.setdefault(coin, []).append({
                    "timestamp": now_iso,
                    "hour": hour_key,
                    "rsi": round(rsi_value, 4),
                    "price": float(info.get("price", 0.0) or 0.0),
                    "flat_count": int(flat_count.get(coin, 0) or 0),
                })
                flat_rsi_history[coin] = flat_rsi_history[coin][-500:]
                print(
                    f"Flat RSI observation: {coin} "
                    f"rsi={rsi_value:.2f} "
                    f"count={flat_count.get(coin, 0)}"
                )

            print(
                f"Flat tracking: {coin} "
                f"count={flat_count.get(coin, 0)} "
                f"since={flat_since.get(coin)}"
            )
        else:
            if coin in flat_count or coin in flat_since:
                print(
                    f"Flat tracking reset: {coin} "
                    f"action={action}"
                )

            flat_count.pop(coin, None)
            flat_since.pop(coin, None)
            flat_last_counted_hour.pop(coin, None)
            flat_rsi_history.pop(coin, None)

    state["flat_count"] = flat_count
    state["flat_since"] = flat_since
    state["flat_last_counted_hour"] = flat_last_counted_hour
    state["flat_rsi_history"] = flat_rsi_history


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
            rsi = calculate_rsi(df["Close"].tolist(), period=14)

            current[ticker] = {
                "signal": last,
                "action": action,
                "price": price,
                "osc": osc,
                # Observation-only: never read by decide_trades().
                "rsi": rsi,
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

    slots = max(0, max_positions - len(remaining))

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
        for stale_coin in stale_owned:
            clear_position_open_time(state, stale_coin)
        owned_coins -= stale_owned

    managed_positions = {
        c: p
        for c, p in open_positions.items()
        if c in owned_coins
    }

    # Observation-only tracking for currently owned positions.
    update_peak_tracking(state, managed_positions, owned_coins)
    update_flat_tracking(state, signals, owned_coins)

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

            fill_totals = get_order_fill_totals(
                info,
                address,
                result.get("oid"),
                coin,
            )

            if fill_totals is not None:
                result["exchange_fee"] = fill_totals["fee"]
                result["exchange_closed_pnl"] = fill_totals["closed_pnl"]
                result["exchange_fill_count"] = fill_totals["fill_count"]
                result["fee_tokens"] = fill_totals["fee_tokens"]
                result["fill_time_ms"] = fill_totals["first_time"]

            if result["action"] == "close":
                previous = managed_positions.get(coin)

                if previous is not None:
                    entry_px = float(previous["entry_px"])
                    fill_px = float(result.get("fill_price", entry_px))
                    fill_size = abs(float(
                        result.get("fill_size", previous["size"])
                    ))

                    if float(previous["size"]) > 0:
                        fallback_gross_pnl = (
                            fill_px - entry_px
                        ) * fill_size
                    else:
                        fallback_gross_pnl = (
                            entry_px - fill_px
                        ) * fill_size

                    if fill_totals is not None:
                        gross_closed_pnl = fill_totals["closed_pnl"]
                        closing_fee = fill_totals["fee"]
                        pnl_source = "hyperliquid_closedPnl"
                    else:
                        gross_closed_pnl = fallback_gross_pnl
                        closing_fee = 0.0
                        pnl_source = "price_fallback"

                    history_so_far = state.get("history", []) or []
                    opening_record = find_latest_open_history_record(
                        history_so_far,
                        coin,
                    )

                    opening_fee = 0.0
                    opening_fee_found = False

                    if opening_record is not None:
                        if "exchange_fee" in opening_record:
                            opening_fee = float(
                                opening_record.get("exchange_fee", 0.0) or 0.0
                            )
                            opening_fee_found = True
                        elif opening_record.get("oid") is not None:
                            opening_totals = get_order_fill_totals(
                                info,
                                address,
                                opening_record.get("oid"),
                                coin,
                            )
                            if opening_totals is not None:
                                opening_fee = opening_totals["fee"]
                                opening_fee_found = True

                    trading_fees = opening_fee + closing_fee

                    funding_info = get_position_funding(
                        state,
                        info,
                        address,
                        coin,
                        (
                            fill_totals.get("last_time")
                            if fill_totals is not None
                            else None
                        ),
                    )
                    funding_pnl = float(
                        funding_info.get("funding_pnl", 0.0) or 0.0
                    )

                    # Final realized trade result:
                    # exchange closed P&L - trading fees + funding.
                    realized_pnl = (
                        gross_closed_pnl
                        - trading_fees
                        + funding_pnl
                    )

                    result["gross_closed_pnl"] = gross_closed_pnl
                    result["opening_fee"] = opening_fee
                    result["closing_fee"] = closing_fee
                    result["trading_fees"] = trading_fees
                    result["funding_pnl"] = funding_pnl
                    result["funding_count"] = funding_info["funding_count"]
                    result["funding_data_complete"] = (
                        funding_info["funding_data_complete"]
                    )
                    result["funding_start_time_ms"] = (
                        funding_info["funding_start_time_ms"]
                    )
                    result["realized_pnl"] = realized_pnl
                    result["pnl_source"] = (
                        f"{pnl_source}+userFunding"
                    )
                    result["fee_data_complete"] = (
                        fill_totals is not None and opening_fee_found
                    )

                    peak_pnl = float(
                        (state.get("peak_pnl", {}) or {}).get(
                            coin,
                            0.0,
                        ) or 0.0
                    )
                    peak_return_pct = float(
                        (state.get("peak_return_pct", {}) or {}).get(
                            coin,
                            0.0,
                        ) or 0.0
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
                        f"    Hyperliquid gross P&L: "
                        f"${gross_closed_pnl:.4f} "
                        f"| trading fees: ${trading_fees:.4f} "
                        f"(open ${opening_fee:.4f} + "
                        f"close ${closing_fee:.4f}) "
                        f"| funding: ${funding_pnl:+.4f}"
                    )
                    print(
                        f"    Net realized P&L: ${realized_pnl:.4f} "
                        f"| peak: ${peak_pnl:.4f} "
                        f"| giveback: ${result['profit_giveback']:.4f} "
                        f"| bot total: "
                        f"${state['realized_pnl_total']:.4f}"
                    )

                    if not result["fee_data_complete"]:
                        print(
                            "    Note: fee history was incomplete; "
                            "net P&L may omit an older opening fee"
                        )

                    if not result["funding_data_complete"]:
                        print(
                            "    Note: funding history start time was "
                            "incomplete; funding P&L may be understated"
                        )

                owned_coins.discard(coin)
                clear_position_open_time(state, coin)
                state.setdefault("peak_pnl", {}).pop(coin, None)
                state.setdefault("peak_return_pct", {}).pop(coin, None)
                state.setdefault("flat_count", {}).pop(coin, None)
                state.setdefault("flat_since", {}).pop(coin, None)
                state.setdefault("flat_last_counted_hour", {}).pop(coin, None)
            else:
                owned_coins.add(coin)
                record_position_open_time(
                    state,
                    coin,
                    fill_totals,
                )

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