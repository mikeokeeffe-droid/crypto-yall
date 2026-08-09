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
}

ASSETS = {
    "BTC-USD": "Bitcoin (BTC)",
    "ETH-USD": "Ethereum (ETH)",
    "SOL-USD": "Solana (SOL)",
    "AVAX-USD": "Avalanche (AVAX)",
    "LINK-USD": "Chainlink (LINK)",
    "SUI20947-USD": "Sui (SUI)",
    "XRP-USD": "XRP",
}

STATE_FILENAME = "crypto_yall_state.json"
POSITION_SIZE_PCT = 0.01  # 1% of segregated capital per trade
MIN_ORDER_NOTIONAL = 12.0  # buffer above Hyperliquid $10 minimum


# ── State Persistence (GitHub Gist) ─────────────────────────────────────────

def load_trading_state() -> dict:
    gist_token = os.environ.get("GIST_TOKEN")
    gist_id = os.environ.get("GIST_ID")
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


def save_trading_state(state: dict):
    gist_token = os.environ.get("GIST_TOKEN")
    gist_id = os.environ.get("GIST_ID")
    if not gist_token or not gist_id:
        return

    requests.patch(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"token {gist_token}"},
        json={"files": {STATE_FILENAME: {"content": json.dumps(state, indent=2)}}},
        timeout=15,
    )


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
    slots_available = max_positions - len(remaining_positions)

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
    calculated_notional = capital * POSITION_SIZE_PCT * leverage
    notional = max(calculated_notional, MIN_ORDER_NOTIONAL)

    # Never let the minimum-order adjustment exceed the bot's available
    # leveraged allocation for this trade.
    max_notional = capital * max(leverage, 1.0)
    if notional > max_notional:
        return {
            **trade,
            "status": "skipped",
            "reason": (
                f"Allocated capital too small for ${MIN_ORDER_NOTIONAL:.2f} "
                "minimum order"
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


# ── Guardrails ──────────────────────────────────────────────────────────────

def check_kill_switch() -> bool:
    """Return True if trading should halt."""
    return os.environ.get("KILL_SWITCH", "ON").upper() == "OFF"


def check_daily_drawdown(
    state: dict,
    current_equity: float,
    threshold_pct: float,
) -> tuple[bool, dict]:
    """Check if today's drawdown exceeds threshold."""
    today = dt.date.today().isoformat()
    day_key = f"day_start_{today}"
    day_start = state.get(day_key)

    update = {}

    if day_start is None:
        update[day_key] = current_equity
        return False, update

    drawdown_pct = (
        (current_equity - day_start) / day_start * 100
        if day_start > 0
        else 0
    )

    if drawdown_pct <= -threshold_pct:
        update["halted_today"] = today
        update["halt_reason"] = (
            f"Daily DD {drawdown_pct:.2f}% exceeded {-threshold_pct}%"
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
        <p style="color:#57606a;margin:0 0 8px 0;">{dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</p>
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
        lines.append(f"*{r['ticker']}* — {r['action']} [{status}]")

        if r.get("status") == "filled":
            lines.append(
                f"  Size: {r.get('fill_size', 0):.6g} @ "
                f"${r.get('fill_price', 0):,.2f}"
            )
        elif r.get("error"):
            lines.append(f"  Error: {r['error']}")

        lines.append(f"  Reason: {r.get('reason', '')}")
        lines.append("")

    lines.append(f"_{dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}_")
    text = "\n".join(lines)

    for chat_id in chat_ids:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
            },
            timeout=15,
        )

        print(f"Telegram response: {resp.status_code} {resp.text}")

        if not resp.ok:
            raise RuntimeError(
                f"Telegram API error {resp.status_code}: {resp.text}"
            )


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    print(f"Trade executor started at {dt.datetime.utcnow().isoformat()}Z")

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

    # Load state and check drawdown
    state = load_trading_state()
    equity = get_account_equity(info, address)
    dd_threshold = float(os.environ.get("DAILY_DD_PCT", "5"))
    halted, state_update = check_daily_drawdown(
        state,
        equity,
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
    capital = float(os.environ.get("SEGREGATED_CAPITAL", "10000"))
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

    trades = decide_trades(
        signals,
        managed_positions,
        max_positions,
    )

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

            if result["action"] == "close":
                owned_coins.discard(coin)
            else:
                owned_coins.add(coin)

    # Append to trade history
    history = state.get("history", [])

    for r in results:
        history.append({
            "timestamp": dt.datetime.utcnow().isoformat() + "Z",
            **{
                k: v
                for k, v in r.items()
                if k not in ("raw",)
            },
        })

    state["history"] = history[-500:]
    state["last_equity"] = equity
    state["last_run"] = dt.datetime.utcnow().isoformat() + "Z"
    state["owned_coins"] = sorted(owned_coins)

    latest_positions = get_open_positions(info, address)
    state["open_positions"] = {
        c: p
        for c, p in latest_positions.items()
        if c in owned_coins
    }

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
