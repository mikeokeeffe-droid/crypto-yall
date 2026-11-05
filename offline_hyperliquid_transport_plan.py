"""Pure configuration gate for a FUTURE read-only Hyperliquid info transport.

This file performs no HTTP, does not load environment variables or secrets,
and is not connected to any executor. It only reviews explicit caller-supplied
configuration. An approved configuration is NOT an authenticated exchange
response, wallet-ownership proof, permission to send a request, or approval
to release a trade fence. Never use this as a live trading authorization.
"""
from dataclasses import dataclass
import re
from urllib.parse import urlsplit


_ACCOUNT = re.compile(r"0x[0-9a-fA-F]{40}\Z")
_ALLOWED = {
    "mainnet": "https://api.hyperliquid.xyz/info",
    "testnet": "https://api.hyperliquid-testnet.xyz/info",
}


@dataclass(frozen=True)
class TransportPlanReview:
    status: str
    reason: str
    endpoint: str | None = None


def review_readonly_transport_plan_offline(*, environment, endpoint,
                                            account, expected_account,
                                            dex, method, request_type,
                                            allow_network=False):
    def hold(reason):
        return TransportPlanReview("hold", reason)

    if allow_network is not False:
        return hold("network execution forbidden in offline plan")
    if type(environment) is not str or environment not in _ALLOWED:
        return hold("unknown exchange environment")
    if type(endpoint) is not str or endpoint != _ALLOWED[environment]:
        return hold("endpoint not pinned to selected environment")
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "https" or parsed.username is not None
            or parsed.password is not None or parsed.query
            or parsed.fragment or parsed.path != "/info"):
        return hold("unsafe endpoint")
    if (type(account) is not str or not _ACCOUNT.fullmatch(account)
            or type(expected_account) is not str
            or account != expected_account):
        return hold("account does not match independently configured scope")
    # Explicitly restrict this first phase to default perp DEX. Additional
    # DEXes, spot, subaccounts and vaults need separate reviewed support.
    if dex != "":
        return hold("non-default DEX unsupported in this offline plan")
    if method != "POST" or request_type not in (
            "orderStatus", "userFillsByTime"):
        return hold("not an approved read-only info query")
    return TransportPlanReview(
        "plan_only",
        "static scope matches; transport, provenance and history unverified",
        endpoint,
    )
