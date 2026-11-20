"""Offline-only shared-account scope comparison.

A matching synthetic scope does NOT authenticate the account, establish
position ownership, acquire a lock or authorize any trade. The current
CI database is keyed only by coin; this module is a future design contract.
No SDK, database, network, wallet or executor imports.
"""
from dataclasses import dataclass
import re

_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}\Z")
_FIELDS = frozenset(("environment", "effective_account", "market_type", "dex", "coin"))


@dataclass(frozen=True)
class AccountScopeReview:
    status: str
    reason: str
    structurally_consistent: bool = False
    submit_authorized: bool = False


def review_account_scope_offline(*, configured, intent, snapshot):
    """Fail closed for any missing/ambiguous scope; matching is never approval."""
    def hold(reason, consistent=False):
        return AccountScopeReview("hold", reason, consistent)

    scopes = (configured, intent, snapshot)
    if any(type(scope) is not dict or set(scope) != _FIELDS for scope in scopes):
        return hold("missing or extra account scope fields")
    expected = configured
    if (expected["environment"] not in ("mainnet", "testnet")
            or expected["market_type"] != "perp"
            or expected["dex"] != ""  # current review supports default perp DEX only
            or type(expected["effective_account"]) is not str
            or _ADDRESS.fullmatch(expected["effective_account"]) is None
            or type(expected["coin"]) is not str
            or not expected["coin"].isascii()
            or not expected["coin"].isalnum()
            or expected["coin"] != expected["coin"].upper()):
        return hold("unsupported or malformed configured account scope")
    if any(type(scope[key]) is not type(expected[key])
           or scope[key] != expected[key]
           for scope in (intent, snapshot) for key in _FIELDS):
        return hold("intent or snapshot disagrees with independently configured scope")

    # Scope strings in dictionaries can be forged; even a perfect match is
    # not a database uniqueness guarantee or authenticated exchange identity.
    return hold("synthetic scope matches, but authenticity and atomic "
                "account-scoped reservation remain unverified", True)
