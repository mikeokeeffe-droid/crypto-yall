"""
hyperliquid_executor.py — Live trading executor for Hyperliquid DEX.

Translates signals from signal_utils into actual trades on Hyperliquid.
Runs daily via GitHub Actions, enforces risk guardrails, and sends
execution notifications.

Required environment variables:
    HL_PRIVATE_KEY      – API wallet private key (trading-only, no withdraw)
    HL_ACCOUNT_ADDRESS  – Main wallet address (0x…) that owns the funds
    HL_TESTNET          – "true" to use testnet, else mainnet
    SEGREGATED_CAPITAL  – USDC allocated to bot (e.g. "10000")
    DAILY_DD_PCT        – Max daily drawdown % before auto-pause (e.g. "5")
    MAX_POSITIONS       – Max concurrent open positions
    KILL_SWITCH         – "OFF" to halt all trading, else trades enabled
    GIST_TOKEN / GIST_ID – State persistence
    GMAIL_USER / GMAIL_APP_PASSWORD / NOTIFY_EMAILS – email alerts
    TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID – telegram alerts
"""

import json
import os
import sys
import time
import datetime as dt
from decimal import Decimal, ROUND_DOWN

import requests
from eth_account import Account

from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

from data_loader import fetch_data
from indicators import compute_all
from hmm_engine import causal_hmm_regimes
from strategy import generate_signals
from backtester import get_asset_profile
from signal_utils import classify_signal


# ── Config ───────────────────────────────────────────────────────────────────

# Map yfinance tickers → Hyperliquid symbols
HL_TICKER_MAP = {
    "BTC-USD": "BTC",
    "ETH-USD": "ETH",
    "SOL-USD": "SOL",
    "AVAX-USD": "AVAX",
    "LINK-USD": "LINK",
    "SUI20947-USD": "SUI",
    "XRP-USD": "XRP",
    "ONDO-USD": "ONDO",
}

ASSETS = {
    "BTC-USD": "Bitcoin (BTC)",
    "ETH-USD": "Ethereum (ETH)",
    "SOL-USD": "Solana (SOL)",
    "AVAX-USD": "Avalanche (AVAX)",
    "LINK-USD": "Chainlink (LINK)",
    "SUI20947-USD": "Sui (SUI)",
    "XRP-USD": "XRP",
    "ONDO-USD": "ONDO",
}

STATE_FILENAME = "crypto_yall_state.json"
POSITION_SIZE_PCT = 0.01  # 1% of segregated capital per trade
MIN_ORDER_NOTIONAL = 12.0  # buffer above Hyperliquid $10 minimum


# ── State Persistence (GitHub Gist) ─────────────────────────────────────────

def load_trading_state() -> dict:
    gist_token = os.environ.get("GIST_TOKEN")
    gist_id = os.environ.get("GIST_ID")

    if not gist_token or not gist_id:
        raise RuntimeError(
            "Cannot load daily state: GIST_TOKEN or GIST_ID is missing"
        )

    try:
        resp = requests.get(
            f"https://api.github.com/gists/{gist_id}",
            headers={"Authorization": f"token {gist_token}"},
            timeout=15,
        )
    except requests.RequestException as e:
        raise RuntimeError(
            f"Failed to load daily state from Gist: {e}"
        ) from e

    if not resp.ok:
        raise RuntimeError(
            f"Failed to load daily state from Gist: "
            f"HTTP {resp.status_code} {resp.text}"
        )

    try:
        files = resp.json().get("files", {})

        if STATE_FILENAME not in files:
            raise KeyError(
                f"{STATE_FILENAME} not found in Daily Gist"
            )

        state = json.loads(
            files[STATE_FILENAME]["content"]
        )

        if not isinstance(state, dict):
            raise TypeError("Daily state is not a JSON object")

    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise RuntimeError(
            f"Daily Gist state is invalid: {e}"
        ) from e

    print("Daily state loaded successfully")
    return state

def save_trading_state(state: dict):
    gist_token = os.environ.get("GIST_TOKEN")
    gist_id = os.environ.get("GIST_ID")
    if not gist_token or not gist_id:
        raise RuntimeError(
            "Cannot save daily state: GIST_TOKEN or GIST_ID is missing"
        )

    resp = requests.patch(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"token {gist_token}"},
        json={"files": {STATE_FILENAME: {"content": json.dumps(state, indent=2)}}},
        timeout=15,
    )

    if not resp.ok:
        raise RuntimeError(
            f"Failed to save daily state to Gist: "
            f"HTTP {resp.status_code} {resp.text}"
        )

    print("Daily state saved successfully")


# ── Hyperliquid Client ──────────────────────────────────────────────────────

def get_client():
    """Return (info, exchange, account_address)."""
    priv_key = os.environ.get("HL_PRIVATE_KEY")
    account_address = os.environ.get("HL_ACCOUNT_ADDRESS")
    is_testnet = os.environ.get("HL_TESTNET", "true").lower() == "true"

    if not priv_key or not account_address:
        raise RuntimeError("HL_PRIVATE_KEY and HL_ACCOUNT_ADDRESS required")

    base_url = constants.TESTNET_API_URL if is_testnet else constants.MAINNET_API_URL
    wallet = Account.from_key(priv_key)
    info = Info(base_url, skip_ws=True)
    exchange = Exchange(wallet, base_url, account_address=account_address)

    return info, exchange, account_address


def get_account_equity(info, address: str) -> float:
    """Return account equity, including Unified Account USDC."""
    state = info.user_state(address)
    equity = float(state["marginSummary"]["accountValue"])

    if equity < 10:
        spot_state = info.spot_user_state(address)
        usdc_balance = next(
            (b for b in spot_state.get("balances", []) if b.get("coin") == "USDC"),
            None,
        )
        if usdc_balance:
            equity = float(usdc_balance.get("total", 0))

    return equity


def get_open_positions(info, address: str) -> dict:
    """Return {coin: {size, entry_px, unrealized_pnl}} for open positions."""
    state = info.user_state(address)
    positions = {}

    for p in state.get("assetPositions", []):
        pos = p["position"]
        size = float(pos["szi"])
        if size == 0:
            continue

        positions[pos["coin"]] = {
            "size": size,  # signed: + long, - short
            "entry_px": float(pos["entryPx"]),
            "unrealized_pnl": float(pos["unrealizedPnl"]),
        }

    return positions


def get_mid_price(info, coin: str) -> float:
    return float(info.all_mids()[coin])


def coin_is_listed(info, coin: str) -> bool:
    """Check if a coin is available for trading on the current environment."""
    return coin in info.all_mids()


# ── Signal Computation ──────────────────────────────────────────────────────

def compute_all_signals() -> dict:
    """Return {ticker: {action, regime, price, bull_conf, signal}}."""
    all_data = fetch_data(tickers=list(ASSETS.keys()))
    current = {}

    for ticker in ASSETS:
        try:
            raw = all_data.get(ticker)
            if raw is None or raw.empty:
                continue

            df = compute_all(raw)
            regimes, bull_probs, bear_probs = causal_hmm_regimes(df)
            profile = get_asset_profile(ticker)

            regime = regimes.iloc[-1] if len(regimes) > 0 else "Unknown"
            price = float(df["Close"].iloc[-1])
            bull_conf = float(bull_probs.iloc[-1]) if len(bull_probs) > 0 else 0.0
            bear_conf = float(bear_probs.iloc[-1]) if len(bear_probs) > 0 else 0.0

            sig = generate_signals(
                df,
                regimes,
                bull_probs=bull_probs,
                bear_probs=bear_probs,
                aggressive=True,
                bull_leverage=profile["max_bull_leverage"],
                allow_short=profile["allow_short"],
                atr_mult=profile["atr_mult"],
            )

            last = int(sig["Signal"].iloc[-1])
            prev = int(sig["Signal"].iloc[-2]) if len(sig) >= 2 else last
            action_key = classify_signal(last, prev, regime)

            current[ticker] = {
                "signal": last,
                "action": action_key,
                "regime": regime,
                "price": price,
                "bull_conf": bull_conf,
                "bear_conf": bear_conf,
                "leverage": float(sig["Leverage"].iloc[-1]) if "Leverage" in sig.columns else 1.0,
            }

        except Exception as e:
            print(f"Error computing signal for {ticker}: {e}")
            continue

    return current


# ── Trade Decisions ─────────────────────────────────────────────────────────

def decide_trades(signals: dict, open_positions: dict, max_positions: int) -> list[dict]:
    """
    Reconcile signals vs current positions and return list of trade intents.

    Each intent: {ticker, hl_coin, action, side, reason}
    action: "open_long" | "open_short" | "close"
    """
    trades = []

    # Step 1: Determine which current positions need to be closed
    for ticker, info in signals.items():
        hl_coin = HL_TICKER_MAP[ticker]
        current_pos = open_positions.get(hl_coin)
        action_key = info["action"]

        if current_pos is None:
            continue

        is_long = current_pos["size"] > 0
        is_short = current_pos["size"] < 0

        should_close = False
        reason = ""

        if action_key == "sell_exit" and is_long:
            should_close = True
            reason = "SELL / EXIT signal"
        elif action_key == "liquidate" and (is_long or is_short):
            should_close = True
            reason = "LIQUIDATE TO CASH signal"
        elif action_key == "cover_short" and is_short:
            should_close = True
            reason = "COVER SHORT signal"
        elif action_key == "buy" and is_short:
            should_close = True
            reason = "Signal flipped long while short"
        elif action_key == "enter_short" and is_long:
            should_close = True
            reason = "Signal flipped short while long"

        if should_close:
            trades.append({
                "ticker": ticker,
                "hl_coin": hl_coin,
                "action": "close",
                "side": "long" if is_long else "short",
                "reason": reason,
            })

    # Step 2: Determine which new positions to open
    closes_by_coin = {t["hl_coin"] for t in trades if t["action"] == "close"}
    remaining_positions = {
        c: p for c, p in open_positions.items() if c not in closes_by_coin
    }
    slots_available = max(0, max_positions - len(remaining_positions))

    open_candidates = []

    for ticker, info in signals.items():
        hl_coin = HL_TICKER_MAP[ticker]
        action_key = info["action"]

        existing = remaining_positions.get(hl_coin)
        if existing:
            continue

        # Only open on a NEW entry signal.
        # A hold_long / hold_short means the strategy was already in that
        # position before this run; we do not "sync" into it mid-trade.
        if action_key == "buy":
            open_candidates.append({
                "ticker": ticker,
                "hl_coin": hl_coin,
                "action": "open_long",
                "side": "long",
                "reason": "BUY signal",
                "confidence": info["bull_conf"],
            })

        elif action_key == "enter_short":
            open_candidates.append({
                "ticker": ticker,
                "hl_coin": hl_coin,
                "action": "open_short",
                "side": "short",
                "reason": "ENTER SHORT signal",
                "confidence": info["bear_conf"],
            })

    open_candidates.sort(key=lambda x: x["confidence"], reverse=True)
    trades.extend(open_candidates[:slots_available])

    return trades


# ── Order Execution ─────────────────────────────────────────────────────────

def round_size(size: float, sz_decimals: int) -> float:
    """Round position size down to the coin's size decimals."""
    if sz_decimals <= 0:
        return float(int(size))

    q = Decimal("1").scaleb(-sz_decimals)
    return float(Decimal(str(size)).quantize(q, rounding=ROUND_DOWN))


def get_size_decimals(info, coin: str) -> int:
    meta = info.meta()

    for universe in meta.get("universe", []):
        if universe["name"] == coin:
            return int(universe["szDecimals"])

    return 3


def execute_trade(info, exchange, trade: dict, capital: float, leverage: float) -> dict:
    """Execute a single trade via Hyperliquid market order."""
    coin = trade["hl_coin"]

    if trade["action"] == "close":
        resp = exchange.market_close(coin)
        return _parse_response(trade, resp, info, coin)

    mid = get_mid_price(info, coin)
    requested_notional = capital * POSITION_SIZE_PCT * leverage
    is_testnet = os.environ.get("HL_TESTNET", "true").lower() == "true"

    # Testnet may raise a tiny simulated order above the exchange minimum.
    # Mainnet must never silently increase real-money risk: if the strategy's
    # requested order is below Hyperliquid's $10 minimum, skip it.
    if is_testnet and requested_notional < MIN_ORDER_NOTIONAL:
        notional = MIN_ORDER_NOTIONAL

        # Keep the existing safety guard: even on testnet, do not let the
        # minimum-order adjustment exceed this bot's leveraged allocation.
        max_notional = capital * max(leverage, 1.0)
        if notional > max_notional:
            return {
                **trade,
                "status": "skipped",
                "reason": (
                    f"Allocated capital too small for "
                    f"${MIN_ORDER_NOTIONAL:.2f} minimum order"
                ),
            }
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
        return {
            **trade,
            "status": "skipped",
            "reason": "Size rounded to zero",
        }

    try:
        exchange.update_leverage(int(leverage), coin, True)
    except Exception as e:
        print(f"Warning: could not set leverage for {coin}: {e}")

    is_buy = trade["action"] == "open_long"
    resp = exchange.market_open(coin, is_buy, size)

    return _parse_response(trade, resp, info, coin)


def _parse_response(trade: dict, resp: dict, info, coin: str) -> dict:
    """Extract fill info from Hyperliquid response."""
    result = {**trade}

    try:
        if resp.get("status") == "ok":
            statuses = resp["response"]["data"]["statuses"]

            for s in statuses:
                if "filled" in s:
                    f = s["filled"]
                    result["status"] = "filled"
                    result["fill_size"] = float(f["totalSz"])
                    result["fill_price"] = float(f["avgPx"])
                    result["oid"] = f.get("oid")
                    return result

                if "error" in s:
                    result["status"] = "error"
                    result["error"] = s["error"]
                    return result

            result["status"] = "unknown"
            result["raw"] = resp
        else:
            result["status"] = "error"
            result["error"] = resp.get("response", str(resp))

    except Exception as e:
        result["status"] = "error"
        result["error"] = f"Parse error: {e} | raw={resp}"

    return result


def get_order_fill_totals(
    info,
    address: str,
    oid,
    coin: str,
    attempts: int = 3,
) -> dict | None:
    """
    Return Hyperliquid's exact fill accounting for one order.

    Partial fills sharing the same order ID are summed.  closedPnl is the
    exchange-reported gross closed P&L; fee is kept separate so the bot can
    calculate net realized P&L after trading fees.
    """
    if oid is None:
        return None

    oid_text = str(oid)

    for attempt in range(attempts):
        try:
            fills = info.user_fills(address)
        except Exception as e:
            print(
                f"Warning: could not read Hyperliquid fills for "
                f"{coin} order {oid}: {e}"
            )
            fills = []

        matching = [
            fill
            for fill in fills
            if str(fill.get("oid")) == oid_text
            and fill.get("coin") == coin
        ]

        if matching:
            fee_tokens = sorted({
                str(fill.get("feeToken", ""))
                for fill in matching
                if fill.get("feeToken")
            })

            fill_times = [
                int(fill.get("time", 0) or 0)
                for fill in matching
                if int(fill.get("time", 0) or 0) > 0
            ]

            return {
                "closed_pnl": sum(
                    float(fill.get("closedPnl", 0.0) or 0.0)
                    for fill in matching
                ),
                "fee": sum(
                    float(fill.get("fee", 0.0) or 0.0)
                    for fill in matching
                ),
                "fee_tokens": fee_tokens,
                "fill_count": len(matching),
                "first_time": min(fill_times) if fill_times else None,
                "last_time": max(fill_times) if fill_times else None,
            }

        if attempt < attempts - 1:
            time.sleep(0.5)

    print(
        f"Warning: Hyperliquid fill details not found for "
        f"{coin} order {oid}; using fallback accounting"
    )
    return None


def find_latest_open_history_record(history: list[dict], coin: str) -> dict | None:
    """Find the most recent filled opening trade for a currently open coin."""
    for item in reversed(history):
        if item.get("hl_coin") != coin:
            continue
        if item.get("status") != "filled":
            continue

        action = item.get("action")
        if action in ("open_long", "open_short"):
            return item

        # If we encounter a completed close first, there should not be an
        # earlier opening record belonging to the current position.
        if action == "close":
            break

    return None



def _history_time_ms(item: dict) -> int | None:
    """Return a history item's best available timestamp in milliseconds."""
    fill_time_ms = item.get("fill_time_ms")
    if fill_time_ms is not None:
        try:
            value = int(fill_time_ms)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass

    raw = item.get("timestamp")
    if not raw:
        return None

    try:
        parsed = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.UTC)
        return int(parsed.timestamp() * 1000)
    except (TypeError, ValueError):
        return None


def get_position_open_time_ms(
    state: dict,
    coin: str,
) -> tuple[int | None, bool]:
    """
    Return the current position's opening time in milliseconds.

    New positions use the persisted exchange fill time. Existing positions
    created before this upgrade fall back to trade history.
    """
    stored = (state.get("position_opened_at_ms", {}) or {}).get(coin)
    if stored is not None:
        try:
            stored_ms = int(stored)
            if stored_ms > 0:
                return stored_ms, True
        except (TypeError, ValueError):
            pass

    fallback_ms = None
    history = state.get("history", []) or []

    for item in reversed(history):
        if item.get("hl_coin") != coin:
            continue
        if item.get("status") != "filled":
            continue

        action = item.get("action")

        if action == "close":
            break

        if action in (
            "open_long",
            "open_short",
            "pyramid_long",
            "pyramid_short",
        ):
            item_ms = _history_time_ms(item)
            if item_ms is not None:
                fallback_ms = item_ms

            if action in ("open_long", "open_short"):
                return item_ms, item_ms is not None

    # If old history was truncated and only a pyramid record remains, use the
    # earliest available point but mark the funding result incomplete.
    return fallback_ms, False


def record_position_open_time(
    state: dict,
    coin: str,
    fill_totals: dict | None,
) -> None:
    """Persist the opening exchange-fill time for funding attribution."""
    opened = state.setdefault("position_opened_at_ms", {})

    if coin in opened:
        return

    fill_time = None
    if fill_totals is not None:
        fill_time = fill_totals.get("first_time")

    if fill_time is None:
        fill_time = int(dt.datetime.now(dt.UTC).timestamp() * 1000)

    opened[coin] = int(fill_time)


def clear_position_open_time(state: dict, coin: str) -> None:
    """Remove funding-attribution state after a completed close."""
    state.setdefault("position_opened_at_ms", {}).pop(coin, None)


def get_position_funding(
    state: dict,
    info,
    address: str,
    coin: str,
    end_time_ms: int | None = None,
) -> dict:
    """
    Sum Hyperliquid funding received/paid while this bot owned the position.

    Positive USDC means funding received; negative USDC means funding paid.
    Cross-bot coin locking makes the coin's funding attributable to the bot
    that owns that position during this window.
    """
    start_time_ms, start_complete = get_position_open_time_ms(state, coin)

    if start_time_ms is None:
        return {
            "funding_pnl": 0.0,
            "funding_count": 0,
            "funding_data_complete": False,
            "funding_start_time_ms": None,
        }

    if end_time_ms is None:
        end_time_ms = int(dt.datetime.now(dt.UTC).timestamp() * 1000)

    try:
        records = info.user_funding_history(
            address,
            int(start_time_ms),
            int(end_time_ms),
        )
    except Exception as e:
        print(
            f"Warning: could not read Hyperliquid funding for "
            f"{coin}: {e}"
        )
        return {
            "funding_pnl": 0.0,
            "funding_count": 0,
            "funding_data_complete": False,
            "funding_start_time_ms": start_time_ms,
        }

    matching = []
    for record in records or []:
        delta = record.get("delta", {}) or {}
        if delta.get("coin") == coin:
            matching.append(record)

    funding_pnl = sum(
        float((record.get("delta", {}) or {}).get("usdc", 0.0) or 0.0)
        for record in matching
    )

    return {
        "funding_pnl": funding_pnl,
        "funding_count": len(matching),
        "funding_data_complete": bool(start_complete),
        "funding_start_time_ms": start_time_ms,
    }


# ── Guardrails ──────────────────────────────────────────────────────────────

def check_kill_switch() -> bool:
    """Return True if trading should halt."""
    return os.environ.get("KILL_SWITCH", "ON").upper() == "OFF"


def check_daily_drawdown(
    state: dict,
    info,
    address: str,
    capital: float,
    threshold_pct: float,
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
    day_key = f"bot_day_start_pnl_{today}"
    start_marker = state.get(day_key)

    update = {
        "last_bot_pnl_marker": pnl_marker,
        "last_bot_unrealized_pnl": unrealized,
        "last_bot_realized_pnl_total": realized_total,
    }

    if start_marker is None:
        update[day_key] = pnl_marker
        update["last_bot_daily_pnl"] = 0.0
        update["last_bot_dd_pct"] = 0.0
        return False, update

    daily_pnl = pnl_marker - float(start_marker)
    drawdown_pct = (
        daily_pnl / capital * 100
        if capital > 0
        else 0.0
    )

    update["last_bot_daily_pnl"] = daily_pnl
    update["last_bot_dd_pct"] = drawdown_pct

    if drawdown_pct <= -threshold_pct:
        update["halted_today"] = today
        update["halt_reason"] = (
            f"Daily bot DD {drawdown_pct:.2f}% exceeded {-threshold_pct}% "
            f"(daily P&L ${daily_pnl:.2f} on ${capital:.2f} capital)"
        )
        return True, update

    return False, update


# ── Notifications ───────────────────────────────────────────────────────────

def send_execution_notifications(results: list[dict], status_summary: str):
    """Send email + telegram notifications for trade executions."""
    if not results and not status_summary:
        return

    try:
        _send_email(results, status_summary)
    except Exception as e:
        print(f"Email send failed: {e}")

    try:
        _send_telegram(results, status_summary)
    except Exception as e:
        print(f"Telegram send failed: {e}")


def _send_email(results: list[dict], status_summary: str):
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    user = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    recipients = os.environ.get("NOTIFY_EMAILS", "")

    if not user or not password or not recipients:
        return

    recipient_list = [e.strip() for e in recipients.split(",")]

    rows = ""

    for r in results:
        status_color = "#1f883d" if r.get("status") == "filled" else "#cf222e"
        fill_px = (
            f"${r.get('fill_price', 0):,.2f}"
            if r.get("status") == "filled"
            else "—"
        )
        fill_sz = (
            f"{r.get('fill_size', 0):.6g}"
            if r.get("status") == "filled"
            else "—"
        )

        rows += f"""
        <tr>
            <td style="padding:10px;border-bottom:1px solid #e1e4e8;color:#1a1a1a;">{r['ticker']}</td>
            <td style="padding:10px;border-bottom:1px solid #e1e4e8;color:#1a1a1a;">{r['action']}</td>
            <td style="padding:10px;border-bottom:1px solid #e1e4e8;color:{status_color};font-weight:bold;">{r.get('status', '?').upper()}</td>
            <td style="padding:10px;border-bottom:1px solid #e1e4e8;color:#1a1a1a;">{fill_sz}</td>
            <td style="padding:10px;border-bottom:1px solid #e1e4e8;color:#1a1a1a;">{fill_px}</td>
            <td style="padding:10px;border-bottom:1px solid #e1e4e8;color:#1a1a1a;">{r.get('reason', '')}</td>
        </tr>"""

    table_or_empty = (
        f"""
        <table style="width:100%;border-collapse:collapse;margin-top:16px;background:#ffffff;">
            <tr style="background:#f6f8fa;color:#57606a;text-transform:uppercase;font-size:0.75em;letter-spacing:0.5px;">
                <th style="padding:10px;text-align:left;">Asset</th>
                <th style="padding:10px;text-align:left;">Action</th>
                <th style="padding:10px;text-align:left;">Status</th>
                <th style="padding:10px;text-align:left;">Size</th>
                <th style="padding:10px;text-align:left;">Fill Price</th>
                <th style="padding:10px;text-align:left;">Reason</th>
            </tr>
            {rows}
        </table>
        """
        if results
        else '<p style="color:#1a1a1a;">No trades executed this cycle.</p>'
    )

    html = f"""
    <div style="font-family:Arial,Helvetica,sans-serif;background:#ffffff;color:#1a1a1a;padding:24px;border:1px solid #e1e4e8;border-radius:8px;max-width:760px;">
        <h2 style="color:#0969da;margin:0 0 8px 0;">Crypto Y'all Trade Execution</h2>
        <p style="color:#57606a;margin:0 0 8px 0;">{dt.datetime.now(dt.UTC).strftime('%Y-%m-%d %H:%M UTC')}</p>
        <p style="color:#1a1a1a;margin:0 0 16px 0;"><strong>Status:</strong> {status_summary}</p>
        {table_or_empty}
    </div>
    """

    msg = MIMEMultipart("alternative")
    filled = sum(1 for r in results if r.get("status") == "filled")
    summary = f"{filled} filled trade(s)" if results else "No trades"
    msg["Subject"] = f"[Crypto Y'all] Execution: {summary}"
    msg["From"] = user
    msg["To"] = ", ".join(recipient_list)
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(user, password)
        server.send_message(msg)

    print(f"Email sent to {recipient_list}")


def _send_telegram(results: list[dict], status_summary: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_ids_raw = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_ids_raw:
        print("Telegram skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing")
        return

    chat_ids = [c.strip() for c in chat_ids_raw.split(",") if c.strip()]

    lines = [
        "*Crypto Y'all Trade Execution*",
        "",
        f"Status: {status_summary}",
        "",
    ]

    for r in results:
        status = r.get("status", "?").upper()
        lines.append(f"{r['ticker']} — {r['action']} [{status}]")

        if r.get("status") == "filled":
            lines.append(
                f"  Size: {r.get('fill_size', 0):.6g} @ "
                f"${r.get('fill_price', 0):,.2f}"
            )

            # On a completed close, show the trade's realized result.
            # Intraday and Aggressive use this same Telegram function, so
            # this automatically applies to all three live bots.
            if r.get("action") == "close" and "realized_pnl" in r:
                realized_pnl = float(r.get("realized_pnl", 0.0) or 0.0)
                pnl_sign = "+" if realized_pnl >= 0 else ""
                lines.append(
                    f"  Net P/L: {pnl_sign}${realized_pnl:.4f}"
                )

                if "trading_fees" in r:
                    trading_fees = float(
                        r.get("trading_fees", 0.0) or 0.0
                    )
                    lines.append(
                        f"  Trading fees: ${trading_fees:.4f}"
                    )

                if "funding_pnl" in r:
                    funding_pnl = float(
                        r.get("funding_pnl", 0.0) or 0.0
                    )
                    funding_sign = "+" if funding_pnl >= 0 else ""
                    lines.append(
                        f"  Funding: {funding_sign}${funding_pnl:.4f}"
                    )

                if "gross_closed_pnl" in r:
                    gross_pnl = float(
                        r.get("gross_closed_pnl", 0.0) or 0.0
                    )
                    gross_sign = "+" if gross_pnl >= 0 else ""
                    lines.append(
                        f"  Gross P/L: {gross_sign}${gross_pnl:.4f}"
                    )

                if "peak_unrealized_pnl" in r:
                    peak_pnl = float(
                        r.get("peak_unrealized_pnl", 0.0) or 0.0
                    )
                    lines.append(
                        f"  Peak unrealized: ${peak_pnl:.4f}"
                    )

                if "profit_giveback" in r:
                    giveback = float(
                        r.get("profit_giveback", 0.0) or 0.0
                    )
                    lines.append(
                        f"  Profit giveback: ${giveback:.4f}"
                    )

        elif r.get("error"):
            lines.append(f"  Error: {r['error']}")

        lines.append(f"  Reason: {r.get('reason', '')}")
        lines.append("")

    lines.append(dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC"))
    text = "\n".join(lines)

    for chat_id in chat_ids:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
            },
            timeout=15,
        )

        print(f"Telegram response: {resp.status_code} {resp.text}")

        if not resp.ok:
            raise RuntimeError(
                f"Telegram API error {resp.status_code}: {resp.text}"
            )



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


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    print(f"Trade executor started at {dt.datetime.now(dt.UTC).isoformat()}")

    # Kill switch check
    if check_kill_switch():
        print("KILL_SWITCH is OFF — halting all trading")
        send_execution_notifications(
            [],
            "KILL SWITCH ACTIVE — no trades executed",
        )
        sys.exit(0)

    try:
        info, exchange, address = get_client()
    except Exception as e:
        print(f"Failed to init Hyperliquid client: {e}")
        send_execution_notifications([], f"CLIENT INIT FAILED: {e}")
        sys.exit(1)

    # Load state and check this bot's own drawdown
    state = load_trading_state()
    equity = get_account_equity(info, address)
    capital = float(os.environ.get("SEGREGATED_CAPITAL", "10000"))
    dd_threshold = float(os.environ.get("DAILY_DD_PCT", "5"))
    halted, state_update = check_daily_drawdown(
        state,
        info,
        address,
        capital,
        dd_threshold,
    )
    state.update(state_update)

    if halted:
        msg = (
            "Daily drawdown triggered — halting today. "
            f"{state_update.get('halt_reason')}"
        )
        print(msg)
        send_execution_notifications([], msg)
        save_trading_state(state)
        sys.exit(0)

    # Check if already halted today
    today = dt.date.today().isoformat()

    if state.get("halted_today") == today:
        print(f"Already halted today: {state.get('halt_reason')}")
        sys.exit(0)

    # Compute signals and decide trades
    signals = compute_all_signals()
    open_positions = get_open_positions(info, address)
    max_positions = int(os.environ.get("MAX_POSITIONS", "4"))

    # Filter out assets not listed on this Hyperliquid environment
    available = set(info.all_mids().keys())
    signals = {
        t: s
        for t, s in signals.items()
        if HL_TICKER_MAP[t] in available
    }

    skipped = [t for t in ASSETS if t not in signals]
    if skipped:
        print(f"Skipping unavailable assets on this env: {skipped}")

    # Ownership tracking: only manage positions this bot opened.
    owned_coins = set(state.get("owned_coins", []))

    # Reconcile stale ownership
    stale_owned = owned_coins - set(open_positions.keys())
    if stale_owned:
        print(f"Dropping stale owned coins (no position on exchange): {stale_owned}")
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
    # Never open/add to a coin that is already open on the shared Hyperliquid
    # account unless this bot owns that coin. This prevents the daily,
    # intraday and aggressive bots from independently claiming the same asset.
    foreign_coins = set(open_positions.keys()) - owned_coins
    if foreign_coins:
        print(f"Cross-bot lock: coins owned elsewhere: {sorted(foreign_coins)}")
        trades = [
            t for t in trades
            if t["action"] == "close" or t["hl_coin"] not in foreign_coins
        ]

    print(
        f"Decided on {len(trades)} trade(s) "
        f"(own {len(owned_coins)} position(s))"
    )

    results = []

    for trade in trades:
        sig_info = signals.get(trade["ticker"], {})
        leverage = max(
            1.0,
            min(sig_info.get("leverage", 1.0), 3.0),
        )

        result = execute_trade(
            info,
            exchange,
            trade,
            capital,
            leverage,
        )

        results.append(result)

        print(
            f"  {result['ticker']} {result['action']}: "
            f"{result.get('status')} "
            f"{result.get('fill_size', '')} @ "
            f"{result.get('fill_price', '')}"
        )

        # Update ownership on successful fills
        if result.get("status") == "filled":
            coin = result["hl_coin"]

            # Attach the exchange's exact fee / closedPnl for this order.
            # This also records opening fees in history so the eventual close
            # can calculate full round-trip trading costs.
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

                    # Price-based gross P&L remains as a safe fallback if
                    # Hyperliquid's fill-history lookup is temporarily missing.
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

                    # Find the opening order for this exact Daily position.
                    # Newer history entries already contain exchange_fee.
                    # For older positions, retrieve the opening fee from
                    # Hyperliquid by the saved opening order ID.
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

                    # Final trade result:
                    # exchange closed P&L - trading fees + funding received/paid.
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
                        float(
                            state.get(
                                "realized_pnl_total",
                                0.0,
                            ) or 0.0
                        )
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
                        f"| giveback: "
                        f"${result['profit_giveback']:.4f} "
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
            else:
                owned_coins.add(coin)
                record_position_open_time(
                    state,
                    coin,
                    fill_totals,
                )

    # Append to trade history
    history = state.get("history", [])

    for r in results:
        history.append({
            "timestamp": dt.datetime.now(dt.UTC).isoformat(),
            **{
                k: v
                for k, v in r.items()
                if k not in ("raw",)
            },
        })

    state["history"] = history[-500:]
    state["last_equity"] = equity
    state["last_run"] = dt.datetime.now(dt.UTC).isoformat()
    state["owned_coins"] = sorted(owned_coins)

    latest_positions = get_open_positions(info, address)
    state["open_positions"] = {
        c: p
        for c, p in latest_positions.items()
        if c in owned_coins
    }

    # Refresh peaks after any fills so newly opened positions are tracked too.
    update_peak_tracking(state, state["open_positions"], owned_coins)

    save_trading_state(state)

    filled_count = sum(1 for r in results if r.get("status") == "filled")
    error_count = sum(1 for r in results if r.get("status") == "error")
    skipped_count = sum(1 for r in results if r.get("status") == "skipped")

    summary = (
        f"{filled_count} filled"
        f" | {error_count} error(s)"
        f" | {skipped_count} skipped"
        f" | Equity: ${equity:,.2f}"
    )
    send_execution_notifications(results, summary)

    print("Done")


if __name__ == "__main__":
    main()