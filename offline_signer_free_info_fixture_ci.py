"""CI-only signer-free substitute for the four core Hyperliquid Info reads.

Provides *synthetic* immutable-in-practice data for evaluating original
strategy market-data helper compatibility without importing live executors.
No HTTP, real Info/Exchange SDK, signing keys, environment access, order
methods, SQL, or claim authority. This is NOT a network client or source of
authenticated exchange state; it cannot be used to approve position ownership.
"""
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

_ACCOUNT = re.compile(r"0x[0-9a-f]{40}\Z", re.ASCII)
_COIN = re.compile(r"[A-Z0-9]+\Z", re.ASCII)
_ENVIRONMENTS = frozenset(("mainnet", "testnet"))


def _nonnegative(raw):
    if type(raw) is not str or not raw or raw.strip() != raw:
        return False
    try:
        number = Decimal(raw)
    except (ValueError, InvalidOperation):
        return False
    return number.is_finite() and number >= 0


def _positive_leverage(raw):
    """Accept a numeric text leverage or documented object-shaped leverage.

    Hyperliquid userState position leverage may be {"type":"cross",
    "value":2}, not just the original fixture's simple "2" string.
    """
    if type(raw) is str:
        return _nonnegative(raw) and Decimal(raw) > 0
    if type(raw) is dict and set(raw) == {"type", "value"}:
        value=raw["value"]
        if raw["type"] not in ("cross", "isolated"):
            return False
        if type(value) is int:
            return value > 0
        if type(value) is str:
            return _nonnegative(value) and Decimal(value) > 0
    return False


def _signed_number(raw):
    if type(raw) is not str or not raw or raw.strip() != raw:
        return False
    try:
        number = Decimal(raw)
    except (ValueError, InvalidOperation):
        return False
    return number.is_finite()


@dataclass(frozen=True)
class OfflineSignerFreeInfoScope:
    environment: str
    account: str


class OfflineSignerFreeInfoFixture:
    """Read-only surface matching core original-bot Info helper calls.

    No method can send an order; caller mutations of returned dictionaries
    do not affect future reads. Snapshot provenance is synthetic by design.
    """
    __slots__ = ("_scope", "_state", "_spot_state", "_mids", "_meta")

    def __init__(self, scope, state, spot_state, mids, meta):
        self._scope = scope
        self._state = deepcopy(state)
        self._spot_state = deepcopy(spot_state)
        self._mids = deepcopy(mids)
        self._meta = deepcopy(meta)

    @property
    def environment(self):
        return self._scope.environment

    @property
    def account(self):
        return self._scope.account

    @property
    def origin_authenticated(self):
        return False

    @property
    def ownership_verified(self):
        return False

    @property
    def submit_authorized(self):
        return False

    def user_state(self, address):
        if type(address) is not str or address != self._scope.account:
            raise PermissionError("unapproved account in offline Info fixture")
        return deepcopy(self._state)

    def spot_user_state(self, address):
        if type(address) is not str or address != self._scope.account:
            raise PermissionError("unapproved spot account")
        return deepcopy(self._spot_state)

    def user_fills(self, address):
        if type(address) is not str or address != self._scope.account:
            raise PermissionError("unapproved fills account")
        # Missing or partial synthetic history is NOT proof of zero fills.
        raise PermissionError("trusted, complete order-fill history unavailable")

    def user_funding_history(self, address, start_time_ms, end_time_ms):
        if type(address) is not str or address != self._scope.account:
            raise PermissionError("unapproved funding account")
        if (type(start_time_ms) is not int
                or type(end_time_ms) is not int
                or start_time_ms <= 0 or end_time_ms < start_time_ms):
            raise PermissionError("invalid requested funding time window")
        raise PermissionError("trusted, complete funding history unavailable")

    def all_mids(self):
        return deepcopy(self._mids)

    def meta(self):
        return deepcopy(self._meta)


def make_signer_free_info_fixture(*, scope, snapshot):
    """Return one strictly scoped, synthetic Info-only client or None.

    No signer, client factory, secret, credential, endpoint or callback can
    be supplied. This prevents the offline compatibility fixture from
    implicitly gaining exchange execution or external data access.
    """
    if (type(scope) is not OfflineSignerFreeInfoScope
            or type(scope.environment) is not str
            or scope.environment not in _ENVIRONMENTS
            or type(scope.account) is not str
            or _ACCOUNT.fullmatch(scope.account) is None
            or type(snapshot) is not dict
            or set(snapshot) != {
                "environment", "account", "user_state", "spot_state",
                "all_mids", "meta",
            }
            or snapshot["environment"] != scope.environment
            or snapshot["account"] != scope.account):
        return None

    state = snapshot["user_state"]
    spot = snapshot["spot_state"]
    mids = snapshot["all_mids"]
    meta = snapshot["meta"]
    if (type(state) is not dict
            or set(state) != {"marginSummary", "assetPositions"}
            or type(state["marginSummary"]) is not dict
            or set(state["marginSummary"]) != {"accountValue"}
            or not _nonnegative(state["marginSummary"]["accountValue"])
            or type(state["assetPositions"]) is not list
            or type(spot) is not dict or set(spot) != {"balances"}
            or type(spot["balances"]) is not list
            or type(mids) is not dict or not mids
            or type(meta) is not dict or set(meta) != {"universe"}
            or type(meta["universe"]) is not list):
        return None

    coins = set()
    for asset in state["assetPositions"]:
        if (type(asset) is not dict or set(asset) != {"position"}
                or type(asset["position"]) is not dict):
            return None
        pos = asset["position"]
        if (set(pos) != {"coin", "szi", "entryPx", "unrealizedPnl", "leverage"}
                or type(pos["coin"]) is not str
                or _COIN.fullmatch(pos["coin"]) is None
                or not _signed_number(pos["szi"])
                or not _nonnegative(pos["entryPx"])
                or not _signed_number(pos["unrealizedPnl"])
                or not _positive_leverage(pos["leverage"])
                or pos["coin"] in coins):
            return None
        coins.add(pos["coin"])
    for balance in spot["balances"]:
        if (type(balance) is not dict or set(balance) != {"coin", "total"}
                or type(balance["coin"]) is not str
                or _COIN.fullmatch(balance["coin"]) is None
                or not _nonnegative(balance["total"])):
            return None

    if any(type(coin) is not str or _COIN.fullmatch(coin) is None
           or not _nonnegative(price) or Decimal(price) == 0
           for coin, price in mids.items()):
        return None
    listed = set()
    for entry in meta["universe"]:
        if (type(entry) is not dict
                or set(entry) != {"name", "szDecimals"}
                or type(entry["name"]) is not str
                or _COIN.fullmatch(entry["name"]) is None
                or type(entry["szDecimals"]) is not int
                or not 0 <= entry["szDecimals"] <= 8
                or entry["name"] in listed):
            return None
        listed.add(entry["name"])
    if not set(mids).issubset(listed) or not coins.issubset(listed):
        return None
    return OfflineSignerFreeInfoFixture(scope, state, spot, mids, meta)
