"""Review-only fixed Hyperliquid Testnet scope. Never network or trading authority.

This isolated component is for the EXISTING three-bot migration in PR #42.
It does not modify or run legacy executors. A future sender must pin the
environment server-side, separately authenticate the account, verify actual
runtime restrictions, and receive explicit operator approval before use.
No env variables, credentials, SDK clients, requests or sockets are accessed.
"""
from dataclasses import dataclass

_TESTNET_API_URL = "https://api.hyperliquid-testnet.xyz"


@dataclass(frozen=True)
class OfflineTestnetScope:
    state: str = "HOLD"
    reason: str = "untrusted network request or runtime not verified"
    network: str | None = None
    api_url: str | None = None
    candidate_parsed: bool = False
    server_scope_verified: bool = False
    account_scope_verified: bool = False
    network_egress_verified: bool = False
    signing_enabled: bool = False
    order_authorized: bool = False
    close_authorized: bool = False


def inspect_testnet_only_scope_offline(*, proposed_network, proposed_api_url=None):
    """Accept only an exact Testnet label; refuse any caller-selected URL.

    The returned endpoint is fixed in this module, never selected using
    HL_TESTNET, a caller-provided endpoint, or Mainnet fallback. A valid
    candidate is still REVIEW_ONLY_HOLD, not permission to connect.
    """
    if (type(proposed_network) is not str
            or proposed_network != "testnet"
            or proposed_api_url is not None):
        return OfflineTestnetScope()
    return OfflineTestnetScope(
        state="REVIEW_ONLY_HOLD",
        reason="fixed testnet proposal; no server authentication or runtime proof",
        network="testnet",
        api_url=_TESTNET_API_URL,
        candidate_parsed=True,
    )
