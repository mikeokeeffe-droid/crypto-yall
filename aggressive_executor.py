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
    AGGRESSIVE_LEVERAGE                 (normal aggressive leverage; defaults to 3x)
    AGGRESSIVE_MAX_LEVERAGE             (large-cap aggressive leverage; defaults to 4x)
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
from aggressive_entry_shadow import score_entry_quality
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
    get_position_funding,
    record_position_open_time,
    clear_position_open_time,
)
from backtester import get_asset_profile


STATE_FILENAME = "aggressive_state.json"
POSITION_SIZE_PCT = 0.015  # 1.5% per trade — higher than standard intraday
PYRAMID_SIZE_PCT = 0.005   # 0.5% extra per pyramid add (max 2 adds)
TESTNET_MIN_ORDER_NOTIONAL = 12.0  # buffer above Hyperliquid $10 minimum
AGGRESSIVE_LEVERAGE = float(os.getenv("AGGRESSIVE_LEVERAGE", "3"))
AGGRESSIVE_MAX_LEVERAGE = float(os.getenv("AGGRESSIVE_MAX_LEVERAGE", "4"))


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

        state_file = files[STATE_FILENAME]
        if state_file.get("truncated"):
            raw_url = state_file.get("raw_url")
            if not raw_url:
                raise ValueError(
                    "Aggressive Gist state is truncated but has no raw_url"
                )
            raw_resp = requests.get(
                raw_url,
                headers={
                    "Authorization": f"token {gist_token}",
                    "Accept": "application/vnd.github.raw",
                },
                timeout=30,
            )
            if not raw_resp.ok:
                raise RuntimeError(
                    "Failed to load full aggressive state from Gist raw_url: "
                    f"HTTP {raw_resp.status_code} {raw_resp.text}"
                )
            state_text = raw_resp.text
            print(
                "Aggressive Gist state exceeded the inline API limit; "
                "loaded complete state from raw_url"
            )
        else:
            state_text = state_file.get("content", "")

        state = json.loads(state_text)

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


def get_position_entry_fees(
    state: dict,
    info,
    address: str,
    coin: str,
) -> tuple[float, bool]:
    """
    Sum all trading fees paid to build the current Aggressive position.

    Includes the original open plus any pyramid adds since the last completed
    close. Older history entries that do not yet contain exchange_fee are
    backfilled from Hyperliquid using their saved order ID.
    """
    history = state.get("history", []) or []
    relevant = []

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
            relevant.append(item)

    if not relevant:
        return 0.0, False

    total_fee = 0.0
    complete = True

    for item in relevant:
        if "exchange_fee" in item:
            total_fee += float(item.get("exchange_fee", 0.0) or 0.0)
            continue

        oid = item.get("oid")
        if oid is None:
            complete = False
            continue

        totals = get_order_fill_totals(
            info,
            address,
            oid,
            coin,
        )

        if totals is None:
            complete = False
            continue

        total_fee += totals["fee"]

    return total_fee, complete


ENTRY_SHADOW_KEYS = (
    "entry_quality",
    "entry_quality_score",
    "entry_type",
    "entry_adx",
    "entry_plus_di",
    "entry_minus_di",
    "entry_atr_pct",
    "entry_vwap_dev_pct",
    "entry_osc",
    "entry_osc_delta",
    "entry_directional_ok",
    "entry_vwap_ok",
    "entry_oscillator_ok",
    "shadow_fresh_only_would_block",
    "shadow_bearish_regime_evaluable",
    "shadow_bearish_regime_would_block",
    "shadow_bearish_regime_rule",
    "shadow_combined_would_block",
    "shadow_market_regime",
    "shadow_dynamic_leverage",
    "shadow_dynamic_leverage_rule",
    "shadow_dual_short_long_block_would_block",
    "shadow_dual_short_btc_short",
    "shadow_dual_short_eth_short",
    "shadow_dual_short_rule",
    "entry_shadow_only",
    "entry_leverage",
)


def get_position_entry_shadow(state: dict, coin: str) -> dict:
    """Return the original filled-entry shadow diagnostics for this position."""
    history = state.get("history", []) or []

    for item in reversed(history):
        if item.get("hl_coin") != coin or item.get("status") != "filled":
            continue

        action = item.get("action")
        if action == "close":
            break

        if action in ("open_long", "open_short"):
            return {
                key: item[key]
                for key in ENTRY_SHADOW_KEYS
                if key in item
            }

    return {}


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
                "_entry_df": df,
                "_entry_signal_df": sig,
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
    protection_only = os.environ.get("AGGRESSIVE_PROTECTION_ONLY", "OFF").upper() == "ON"
    if protection_only:
        print("Aggressive PROTECTION-ONLY mode: no entries, pyramids, normal signal exits, or signal recomputation")

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
    if protection_only:
        # A daily drawdown halt blocks new trading, but must not disable
        # protection for positions the bot already owns.
        print("Protection-only mode: bypassing daily drawdown entry halt")
    else:
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

    if protection_only:
        # Use only the last signals confirmed by the normal 30-minute executor.
        # This prevents a 5-minute protection check from releasing re-entry
        # locks based on a still-forming 30-minute candle.
        signals = state.get("last_signals", {}) or {}
        print(f"Protection-only mode: using {len(signals)} last confirmed Aggressive signal(s)")
    else:
        signals = compute_aggressive_signals()

    open_positions = get_open_positions(info, address)
    max_positions = int(os.environ.get("AGGRESSIVE_MAX_POSITIONS", "4"))

    # Normal runs verify market availability. Protection-only runs avoid
    # unnecessary market/signal work and keep only known persisted symbols.
    if protection_only:
        signals = {t: s for t, s in signals.items() if t in HL_SYMBOL_MAP}
    else:
        available = set(info.all_mids().keys())
        signals = {t: s for t, s in signals.items() if HL_SYMBOL_MAP[t] in available}
        skipped = [t for t in ASSETS if t not in signals]
        if skipped:
            print(f"Skipping unavailable assets on this env: {skipped}")

    # Ownership tracking with stale-position reconciliation.
    # Recover any entry that filled on Hyperliquid after we persisted a
    # pre-order claim but before the post-fill state save completed.
    owned_coins = set(state.get("owned_coins", []))
    pending_claims = state.get("pending_entry_claims", {}) or {}
    for pending_coin, claim in list(pending_claims.items()):
        pos = open_positions.get(pending_coin)
        if pos is None:
            pending_claims.pop(pending_coin, None)
            continue
        claimed_side = str((claim or {}).get("side", "")).lower()
        actual_side = "long" if float(pos.get("size", 0.0) or 0.0) > 0 else "short"
        if claimed_side == actual_side:
            if pending_coin not in owned_coins:
                print(
                    f"Recovered Aggressive ownership for {pending_coin} "
                    f"from persisted pending entry claim"
                )
            owned_coins.add(pending_coin)
            pending_claims.pop(pending_coin, None)
    state["pending_entry_claims"] = pending_claims

    stale_owned = owned_coins - set(open_positions.keys())
    if stale_owned:
        print(f"Dropping stale owned coins (no position on exchange): {stale_owned}")
        for stale_coin in stale_owned:
            clear_position_open_time(state, stale_coin)
        owned_coins -= stale_owned

    managed_positions = {c: p for c, p in open_positions.items() if c in owned_coins}

    # Observation-only peak-profit tracking for currently owned positions.
    update_peak_tracking(state, managed_positions, owned_coins)

    # Per-coin pyramid state (persisted across runs)
    pyramid_state = state.get("pyramid_state", {})

    trades = decide_trades(signals, managed_positions, max_positions, pyramid_state)

    # LIVE BTC+ETH dual-short long gate:
    # If Aggressive already owns BOTH BTC and ETH shorts, do not open or
    # pyramid LONG positions in the mid-cap basket. Existing mid-cap longs
    # are not force-closed; normal exit/profit-protection logic still manages
    # them. This gate does not enable mid-cap shorting.
    midcap_coins = {"SOL", "AVAX", "LINK", "SUI", "XRP", "ONDO"}
    btc_pos = managed_positions.get("BTC")
    eth_pos = managed_positions.get("ETH")
    btc_short_live = bool(
        btc_pos and float(btc_pos.get("size", 0.0) or 0.0) < 0
    )
    eth_short_live = bool(
        eth_pos and float(eth_pos.get("size", 0.0) or 0.0) < 0
    )
    dual_short_gate_live = btc_short_live and eth_short_live
    if dual_short_gate_live:
        blocked = [
            t for t in trades
            if t.get("hl_coin") in midcap_coins
            and t.get("action") in ("open_long", "pyramid_long")
        ]
        if blocked:
            print(
                "BTC+ETH DUAL-SHORT LIVE GATE: blocking mid-cap long(s): "
                + ", ".join(t["hl_coin"] for t in blocked)
            )
        trades = [
            t for t in trades
            if not (
                t.get("hl_coin") in midcap_coins
                and t.get("action") in ("open_long", "pyramid_long")
            )
        ]

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
        # Aggressive leverage is controlled by repository/environment variables.
        # Mid-cap / volatile assets use the normal setting; large caps use the max setting.
        # Hyperliquid may apply a lower market-specific cap where required.
        profile = get_asset_profile(trade["ticker"])
        is_large_cap = float(profile.get("max_bull_leverage", 1.5)) >= 3.0
        leverage = AGGRESSIVE_MAX_LEVERAGE if is_large_cap else AGGRESSIVE_LEVERAGE
        leverage = max(1.0, min(leverage, AGGRESSIVE_MAX_LEVERAGE))

        # Persist ownership intent BEFORE a new external order is submitted.
        # If Hyperliquid fills but a later Gist write fails, the next run can
        # safely recover this bot's ownership instead of orphaning the position.
        is_new_entry = trade.get("action") in ("open_long", "open_short")
        if is_new_entry:
            state.setdefault("pending_entry_claims", {})[trade["hl_coin"]] = {
                "side": trade.get("side"),
                "created_at": dt.datetime.now(dt.UTC).isoformat(),
            }
            state["owned_coins"] = sorted(owned_coins)
            save_state(state)

        result = execute_trade(info, exchange, trade, capital, leverage)

        if is_new_entry and result.get("status") != "filled":
            state.setdefault("pending_entry_claims", {}).pop(trade["hl_coin"], None)
            save_state(state)

        # Observation only: score newly filled Aggressive entries.
        if (
            result.get("status") == "filled"
            and result.get("action") in ("open_long", "open_short")
        ):
            signal_info = signals.get(trade["ticker"], {})
            entry_type = (
                "sync_hold"
                if str(trade.get("reason", "")).startswith("sync to ")
                else "fresh_signal"
            )
            shadow = score_entry_quality(
                signal_info.get("_entry_df"),
                signal_info.get("_entry_signal_df"),
                trade["side"],
                entry_type,
            )
            result.update(shadow)

            # Record BTC+ETH direction-gate context on entries that remain
            # eligible after the live gate.
            midcap_coins = {"SOL", "AVAX", "LINK", "SUI", "XRP", "ONDO"}
            btc_pos = managed_positions.get("BTC")
            eth_pos = managed_positions.get("ETH")
            btc_short = bool(btc_pos and float(btc_pos.get("size", 0.0) or 0.0) < 0)
            eth_short = bool(eth_pos and float(eth_pos.get("size", 0.0) or 0.0) < 0)
            dual_short_block = bool(
                trade["side"] == "long"
                and trade["hl_coin"] in midcap_coins
                and btc_short
                and eth_short
            )
            result["shadow_dual_short_btc_short"] = btc_short
            result["shadow_dual_short_eth_short"] = eth_short
            result["shadow_dual_short_long_block_would_block"] = dual_short_block
            result["shadow_dual_short_rule"] = (
                "LIVE: block NEW SOL/AVAX/LINK/SUI/XRP/ONDO longs and long "
                "pyramids when Aggressive owns both BTC and ETH shorts"
            )
            result["entry_leverage"] = leverage
            print(
                f"    Entry Quality Shadow: {shadow.get('entry_quality')} "
                f"{shadow.get('entry_quality_score', 0):.0f}/100 | "
                f"{entry_type} | {leverage:.0f}x | observation only"
            )
            print(
                "    Entry Filter Shadow: "
                f"fresh-only={'BLOCK' if shadow.get('shadow_fresh_only_would_block') else 'ALLOW'} | "
                f"bearish-long={'BLOCK' if shadow.get('shadow_bearish_regime_would_block') else 'ALLOW'} | "
                f"combined={'BLOCK' if shadow.get('shadow_combined_would_block') else 'ALLOW'} | "
                "observation only"
            )
            print(
                "    Dynamic Leverage Shadow: "
                f"{shadow.get('shadow_market_regime', 'UNKNOWN')} -> "
                f"{float(shadow.get('shadow_dynamic_leverage', leverage)):.0f}x "
                f"(live remains {leverage:.0f}x) | observation only"
            )
            print(
                "    BTC+ETH Dual-Short Long Gate: "
                f"BTC-short={btc_short} | ETH-short={eth_short} | "
                f"{'BLOCK' if dual_short_block else 'ALLOW'} | LIVE"
            )

        results.append(result)
        print(f"  {result['ticker']} {result['action']}: {result.get('status')}")

        if result.get("status") == "filled":
            coin = result["hl_coin"]

            # Store Hyperliquid's exact fee / closedPnl for every order.
            # This includes opening orders and pyramid adds so the eventual
            # close can calculate complete round-trip trading costs.
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

                    # Price-based fallback only. Hyperliquid closedPnl is
                    # preferred because it reflects the exchange's own fill
                    # accounting across the whole position.
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

                    entry_fees, entry_fees_complete = get_position_entry_fees(
                        state,
                        info,
                        address,
                        coin,
                    )

                    trading_fees = entry_fees + closing_fee

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

                    # Final realized position result:
                    # exchange closed P&L - all entry/pyramid/close fees
                    # + funding received/paid while this bot owned the coin.
                    realized_pnl = (
                        gross_closed_pnl
                        - trading_fees
                        + funding_pnl
                    )

                    result["gross_closed_pnl"] = gross_closed_pnl
                    result["entry_and_pyramid_fees"] = entry_fees
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
                        fill_totals is not None
                        and entry_fees_complete
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
                    result["profit_giveback"] = max(0.0, peak_pnl - max(realized_pnl, 0.0))

                    # Carry the original entry-quality research fields onto the
                    # close record so wins/losses can be analysed directly by
                    # STRONG/MEDIUM/WEAK and fresh-vs-sync entry type.
                    result.update(get_position_entry_shadow(state, coin))

                    state["realized_pnl_total"] = (
                        float(state.get("realized_pnl_total", 0.0) or 0.0)
                        + realized_pnl
                    )

                    print(
                        f"    Hyperliquid gross P&L: "
                        f"${gross_closed_pnl:.4f} "
                        f"| trading fees: ${trading_fees:.4f} "
                        f"(entries/pyramids ${entry_fees:.4f} + "
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
                            "net P&L may omit an older entry/pyramid fee"
                        )

                    if not result["funding_data_complete"]:
                        print(
                            "    Note: funding history start time was "
                            "incomplete; funding P&L may be understated"
                        )

                owned_coins.discard(coin)
                clear_position_open_time(state, coin)
                pyramid_state.pop(coin, None)
                state.setdefault("peak_pnl", {}).pop(coin, None)
                state.setdefault("peak_return_pct", {}).pop(coin, None)
            elif result["action"].startswith("pyramid_"):
                pyramid_state[coin] = pyramid_state.get(coin, 0) + 1
            else:
                owned_coins.add(coin)
                state.setdefault("pending_entry_claims", {}).pop(coin, None)
                pyramid_state[coin] = 0
                record_position_open_time(
                    state,
                    coin,
                    fill_totals,
                )
                # Save the ownership immediately after a confirmed fill,
                # before non-essential accounting/notification work continues.
                state["owned_coins"] = sorted(owned_coins)
                state["pyramid_state"] = pyramid_state
                save_state(state)

    history = state.get("history", [])
    for r in results:
        history.append({
            "timestamp": dt.datetime.now(dt.UTC).isoformat(),
            **{k: v for k, v in r.items() if k != "raw"},
        })
    state["history"] = history[-500:]

    # Closed-trade win/loss percentages from retained bot history.
    closed = [
        h for h in state["history"]
        if h.get("action") == "close"
        and h.get("status") == "filled"
        and h.get("realized_pnl") is not None
    ]
    wins = sum(1 for h in closed if float(h.get("realized_pnl", 0.0) or 0.0) > 0)
    losses = sum(1 for h in closed if float(h.get("realized_pnl", 0.0) or 0.0) < 0)
    breakeven = max(0, len(closed) - wins - losses)
    decided = wins + losses
    win_pct = (wins / decided * 100.0) if decided else 0.0
    loss_pct = (losses / decided * 100.0) if decided else 0.0
    gross_winning_dollars = sum(
        float(h.get("realized_pnl", 0.0) or 0.0)
        for h in closed
        if float(h.get("realized_pnl", 0.0) or 0.0) > 0
    )
    gross_losing_dollars = sum(
        float(h.get("realized_pnl", 0.0) or 0.0)
        for h in closed
        if float(h.get("realized_pnl", 0.0) or 0.0) < 0
    )
    net_closed_dollars = gross_winning_dollars + gross_losing_dollars

    state["closed_trade_stats"] = {
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "win_pct": win_pct,
        "loss_pct": loss_pct,
        "profit_dollars": gross_winning_dollars,
        "loss_dollars": gross_losing_dollars,
        "net_dollars": net_closed_dollars,
    }
    state["last_equity"] = equity
    state["last_run"] = dt.datetime.now(dt.UTC).isoformat()
    state["owned_coins"] = sorted(owned_coins)
    state["pyramid_state"] = pyramid_state
    latest = get_open_positions(info, address)
    state["open_positions"] = {c: p for c, p in latest.items() if c in owned_coins}

    # Refresh peaks after any fills so newly opened positions get tracked too.
    update_peak_tracking(state, state["open_positions"], owned_coins)

    if not protection_only:
        state["last_signals"] = {
            ticker: {
                k: v for k, v in signal_info.items()
                if not k.startswith("_entry_")
            }
            for ticker, signal_info in signals.items()
        }
    save_state(state)

    filled_count = sum(1 for r in results if r.get("status") == "filled")
    error_count = sum(1 for r in results if r.get("status") == "error")
    skipped_count = sum(1 for r in results if r.get("status") == "skipped")
    summary = (
        f"{filled_count} aggressive filled"
        f" | {error_count} error(s)"
        f" | {skipped_count} skipped"
        f" | Equity: ${equity:,.2f}"
        f" | W/L: {win_pct:.1f}%/{loss_pct:.1f}%"
        f" | P/L$: +${gross_winning_dollars:.2f}/${gross_losing_dollars:.2f}"
        f" | Net: ${net_closed_dollars:+.2f}"
    )
    if results:
        _send_email(results, summary)
        _send_telegram(results, summary)
    print("Done")


if __name__ == "__main__":
    main()