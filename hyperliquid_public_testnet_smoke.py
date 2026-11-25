"""Read-only public Hyperliquid TESTNET connectivity smoke test.

Uses only public info API queries. No wallet, keys, signing, or orders.
"""
import json
import urllib.request

URL = "https://api.hyperliquid-testnet.xyz/info"


def check_public_testnet(*, opener=urllib.request.urlopen):
    payload = json.dumps({"type": "meta"}).encode("utf-8")
    req = urllib.request.Request(
        URL, data=payload, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with opener(req, timeout=15) as response:
        result = json.load(response)
    universe = result.get("universe") if isinstance(result, dict) else None
    if not isinstance(universe, list) or not universe:
        raise RuntimeError("Testnet metadata response missing nonempty universe")
    symbols = [item.get("name") for item in universe if isinstance(item, dict)]
    if not any(isinstance(symbol, str) and symbol for symbol in symbols):
        raise RuntimeError("No recognizable market symbols in metadata")
    return len(symbols)


if __name__ == "__main__":
    count = check_public_testnet()
    print(f"PASS: Hyperliquid testnet public metadata accessible; markets={count}")
