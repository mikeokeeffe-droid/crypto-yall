"""OFFLINE documented Hyperliquid /info response -> signer-free helper snapshot.

Pure response-shape projection only: no transport, signing key, exchange SDK,
account access, database, orders, or authentication. Raw inputs are SYNTHETIC.
The result is a *fixture*, not verified source, complete history, bot ownership,
or permission to trade. Unknown real API fields are discarded rather than
carried into the bot-visible minimal shape.

The original read-only helpers need margin accountValue, net perp positions,
spot balances, perp mids and szDecimals. Hyperliquid's real schemas also
contain margin tables, assetPosition.type, cumFunding, liquidationPx,
leverage.rawUsd, spot hold/locked and many other metadata fields.
"""
from decimal import Decimal, InvalidOperation
import re

from offline_signer_free_info_fixture_ci import (
    OfflineSignerFreeInfoScope, make_signer_free_info_fixture,
)

_COIN = re.compile(r"[A-Z0-9]+\Z", re.ASCII)


def _decimal_text(value, *, allow_zero=True, signed=False):
    if type(value) not in (str, int) or type(value) is bool:
        return None
    raw = str(value)
    if not raw or raw != raw.strip():
        return None
    try:
        d = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if not d.is_finite() or (not signed and d < 0) or (not allow_zero and d == 0):
        return None
    return raw


def _leverage_minimal(value):
    if type(value) is dict:
        # Extra official fields such as isolated rawUsd are not authority.
        if value.get("type") not in ("cross", "isolated"):
            return None
        value = value.get("value")
    text = _decimal_text(value, allow_zero=False)
    return text


def project_offline_documented_info_snapshot(*, scope, clearinghouse_state,
                                              spot_state, all_mids, meta):
    """Normalize *synthetic documented-format* responses or return None.

    Do not interpret the content as authenticated Hyperliquid data.
    Account/environment must be independently pinned. The API reply itself
    cannot establish origin, account control or complete order/fill coverage.
    """
    if (type(scope) is not OfflineSignerFreeInfoScope
            or scope.environment != "testnet"
            or type(clearinghouse_state) is not dict
            or type(spot_state) is not dict
            or type(all_mids) is not dict
            or type(meta) is not dict):
        return None

    summary = clearinghouse_state.get("marginSummary")
    positions = clearinghouse_state.get("assetPositions")
    balances = spot_state.get("balances")
    universe = meta.get("universe")
    if (type(summary) is not dict or type(positions) is not list
            or type(balances) is not list or type(universe) is not list
            or not isinstance(all_mids, dict)):
        return None
    account_value = _decimal_text(summary.get("accountValue"))
    if account_value is None:
        return None

    clean_universe = []
    coins = set()
    for asset in universe:
        if type(asset) is not dict:
            return None
        name = asset.get("name")
        size_digits = asset.get("szDecimals")
        if (type(name) is not str or _COIN.fullmatch(name) is None
                or name in coins or type(size_digits) is not int
                or not 0 <= size_digits <= 8):
            return None
        coins.add(name)
        clean_universe.append({"name": name, "szDecimals": size_digits})

    clean_positions = []
    seen = set()
    for entry in positions:
        if type(entry) is not dict or type(entry.get("position")) is not dict:
            return None
        raw = entry["position"]
        name = raw.get("coin")
        if type(name) is not str or name not in coins or name in seen:
            return None
        seen.add(name)
        size = _decimal_text(raw.get("szi"), signed=True)
        price = _decimal_text(raw.get("entryPx"))
        pnl = _decimal_text(raw.get("unrealizedPnl"), signed=True)
        leverage = _leverage_minimal(raw.get("leverage"))
        if size is None or price is None or pnl is None or leverage is None:
            return None
        clean_positions.append({"position": {
            "coin": name, "szi": size, "entryPx": price,
            "unrealizedPnl": pnl, "leverage": leverage,
        }})

    clean_balances = []
    seen_balances = set()
    for raw in balances:
        if type(raw) is not dict:
            return None
        name = raw.get("coin")
        total = _decimal_text(raw.get("total"))
        if (type(name) is not str or _COIN.fullmatch(name) is None
                or name in seen_balances or total is None):
            return None
        seen_balances.add(name)
        clean_balances.append({"coin":name, "total":total})

    clean_mids = {}
    for name in coins:
        if name not in all_mids:
            continue
        value = _decimal_text(all_mids[name], allow_zero=False)
        if value is None:
            return None
        clean_mids[name] = value
    if not clean_mids:
        return None

    result = {
        "environment":scope.environment,
        "account":scope.account,
        "user_state":{
            "marginSummary":{"accountValue":account_value},
            "assetPositions":clean_positions,
        },
        "spot_state":{"balances":clean_balances},
        "all_mids":clean_mids,
        "meta":{"universe":clean_universe},
    }
    # Reuse the existing strict consumer rather than growing an alternate
    # bot-facing model. It remains synthetic, unsigned and non-authorizing.
    return result if make_signer_free_info_fixture(
        scope=scope, snapshot=result,
    ) is not None else None
