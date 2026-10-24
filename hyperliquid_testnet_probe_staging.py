"""Explicit opt-in, read-only Hyperliquid TESTNET evidence probe.

No exchange key, wallet signing, Supabase credentials, or order submission.
Not imported by any executor and not scheduled by GitHub Actions.
Invoke manually with --address <public-wallet-address> after review.
"""
import argparse
import json
import urllib.request

from hyperliquid_position_snapshot_staging import inspect_user_state_position

TESTNET_INFO = "https://api.hyperliquid-testnet.xyz/info"


def fetch_info(request_type: str, address: str, *, opener=urllib.request.urlopen):
    if request_type not in ("clearinghouseState", "openOrders", "userFills"):
        raise ValueError("Only read-only Hyperliquid info endpoints are allowed")
    payload = json.dumps({"type": request_type, "user": address}).encode("utf-8")
    request = urllib.request.Request(
        TESTNET_INFO, data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with opener(request, timeout=10) as response:
        return json.load(response)


def probe(address: str, coin: str, *, fetch=fetch_info):
    if not (address.startswith("0x") and len(address) == 42
            and all(ch in "0123456789abcdefABCDEF" for ch in address[2:])):
        raise ValueError("Expected public 0x-prefixed 20-byte wallet address")
    if not coin or not coin.isalnum() or coin.upper() != coin:
        raise ValueError("Expected uppercase coin symbol")
    state = fetch("clearinghouseState", address)
    orders = fetch("openOrders", address)
    fills = fetch("userFills", address)
    position = inspect_user_state_position(state, coin, snapshot_fresh=True)
    if not isinstance(orders, list) or not isinstance(fills, list):
        raise ValueError("Unexpected exchange response shape")
    # Do not print wallet address, full positions, fills, or private data.
    return {
        "network": "testnet",
        "coin": coin,
        "position_snapshot_valid": position.valid,
        "position_flat": position.flat if position.valid else None,
        "coin_open_order_count": sum(
            1 for order in orders if isinstance(order, dict)
            and order.get("coin") == coin
        ),
        "coin_fill_records_seen": sum(
            1 for fill in fills if isinstance(fill, dict)
            and fill.get("coin") == coin
        ),
        "warning": "Read-only observations, not verified reconciliation or permission to trade",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True, help="Public testnet wallet address")
    parser.add_argument("--coin", default="BTC")
    args = parser.parse_args()
    print(json.dumps(probe(args.address, args.coin), indent=2))


if __name__ == "__main__":
    main()
