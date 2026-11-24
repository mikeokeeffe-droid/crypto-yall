"""Standalone, unscheduled Hyperliquid TESTNET account reader for security review.

REVIEW ONLY. NOT DEPLOYED OR AUTHORIZED TO RUN ON HETZNER.
Never import or call trading bot executors, signers, /exchange, or Mainnet.
No credentials are needed. stdout reports only counts (not raw positions).
"""
import argparse
import http.client
import json
import re
import ssl
import sys

HOST = "api.hyperliquid-testnet.xyz"
PATH = "/info"
WALLET = "0xF14348Bdf59BA186F9CdD0fC5F369e1f6D3b7dC0"
MAX_RESPONSE_BYTES = 512 * 1024
TIMEOUT_SECONDS = 8


def body_for(kind):
    if kind not in ("clearinghouseState", "openOrders"):
        raise ValueError("unapproved info request")
    return json.dumps(
        {"type": kind, "user": WALLET, "dex": ""},
        separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")


def fetch_info(kind, *, connection_factory=None):
    """One fixed HTTPS POST /info, pinned Testnet host, strict response limits.

    HTTPSConnection ignores HTTPS_PROXY/HTTP_PROXY environment variables.
    Default TLS context validates server certificate and hostname.
    """
    request = body_for(kind)
    if connection_factory is None:
        connection_factory = lambda: http.client.HTTPSConnection(
            HOST, 443, context=ssl.create_default_context(), timeout=TIMEOUT_SECONDS
        )
    conn = connection_factory()
    try:
        conn.request(
            "POST", PATH, body=request,
            headers={"Content-Type": "application/json",
                     "Accept": "application/json",
                     "Connection": "close"},
        )
        response = conn.getresponse()
        if response.status != 200:
            raise ValueError("Testnet API rejected read-only request")
        length = response.getheader("Content-Length")
        if length is not None:
            if not re.fullmatch(r"[0-9]+", length) or int(length) > MAX_RESPONSE_BYTES:
                raise ValueError("response too large")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("response too large")
        data = json.loads(raw.decode("utf-8"))
        if kind == "openOrders":
            if not isinstance(data, list) or len(data) > 5000:
                raise ValueError("invalid openOrders response")
            return len(data)
        if not isinstance(data, dict) or not isinstance(data.get("assetPositions"), list):
            raise ValueError("invalid clearinghouseState response")
        if len(data["assetPositions"]) > 5000:
            raise ValueError("invalid position count")
        return len(data["assetPositions"])
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="One-time TESTNET /info counts; NO trading")
    parser.add_argument("--manual-review-only", action="store_true")
    args = parser.parse_args(argv)
    if not args.manual_review_only:
        print("HOLD: explicit manual-review-only flag required", file=sys.stderr)
        return 2
    # Exact two fixed public read-only calls. No retries and no state writes.
    try:
        positions = fetch_info("clearinghouseState")
        orders = fetch_info("openOrders")
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        print("HOLD: Testnet read-only check failed", file=sys.stderr)
        return 1
    print(f"TESTNET READ ONLY: positions={positions}; open_orders={orders}; no trade authority")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
