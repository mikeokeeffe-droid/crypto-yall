"""
test_trade.py — One-off test trade on Hyperliquid testnet.

Places a tiny BTC long, waits, then closes it.
"""

import os
import time

from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants


def main():
    priv_key = os.environ.get("HL_PRIVATE_KEY")
    account_address = os.environ.get("HL_ACCOUNT_ADDRESS")
    is_testnet = os.environ.get("HL_TESTNET", "true").lower() == "true"

    if not priv_key or not account_address:
        print("ERROR: HL_PRIVATE_KEY and HL_ACCOUNT_ADDRESS must be set")
        return

    base_url = (
        constants.TESTNET_API_URL
        if is_testnet
        else constants.MAINNET_API_URL
    )

    print(f"Connecting to: {base_url}")
    print(f"Account: {account_address}")

    wallet = Account.from_key(priv_key)
    info = Info(base_url, skip_ws=True)
    exchange = Exchange(
        wallet,
        base_url,
        account_address=account_address
    )

    # 1. Check perp account state
    state = info.user_state(account_address)
    equity = float(state["marginSummary"]["accountValue"])
    withdrawable = float(state.get("withdrawable", 0))

    # Unified Account fallback:
    # if perp balance is zero, check USDC spot balance.
    if equity < 10:
        spot_state = info.spot_user_state(account_address)

        usdc_balance = next(
            (
                balance
                for balance in spot_state.get("balances", [])
                if balance.get("coin") == "USDC"
            ),
            None,
        )

        if usdc_balance:
            equity = float(usdc_balance.get("total", 0))
            held = float(usdc_balance.get("hold", 0))
            withdrawable = max(0.0, equity - held)

            print("Using Unified Account USDC balance")

    print(f"Account equity: ${equity:.2f}")
    print(f"Withdrawable:   ${withdrawable:.2f}")

    # 2. Get BTC mid price
    mids = info.all_mids()
    btc_mid = float(mids["BTC"])

    print(f"BTC mid price: ${btc_mid:,.2f}")

    if equity < 10:
        print("\nAccount has insufficient balance for a test trade.")
        print("API connection confirmed working:")
        print(f"- Authenticated as {account_address}")
        print("- Read account state successfully")
        print("- Read market data successfully")
        return

    # 3. Place a small BTC long
    size = round(15 / btc_mid, 5)

    print(f"\nPlacing test LONG: {size} BTC @ market")

    try:
        exchange.update_leverage(2, "BTC", True)
    except Exception as e:
        print(f"Leverage set warning: {e}")

    resp = exchange.market_open(
        "BTC",
        True,
        size
    )

    print(f"Open response: {resp}")

    time.sleep(3)

    # 4. Check BTC position
    state = info.user_state(account_address)

    positions = [
        p["position"]
        for p in state.get("assetPositions", [])
        if p["position"]["coin"] == "BTC"
    ]

    if positions:
        print(f"Position confirmed: {positions[0]}")
    else:
        print("No BTC position found after order.")

    # 5. Close BTC position
    print("\nClosing position...")

    close_resp = exchange.market_close("BTC")

    print(f"Close response: {close_resp}")

    # 6. Final account state
    time.sleep(3)

    final_state = info.user_state(account_address)

    final_perp_equity = float(
        final_state["marginSummary"]["accountValue"]
    )

    print(f"\nFinal perp equity: ${final_perp_equity:.2f}")
    print("Test trade completed.")


if __name__ == "__main__":
    main()
