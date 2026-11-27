"""Compile an exact TESTNET SOL protected order into official SDK wire form.

OFFLINE REVIEW ONLY. Imports SDK encoding helpers, NOT Exchange, Info,
sign_l1_action, wallet or transport. No network or filesystem writes.

Requires a deterministic already-reviewed bracket/client ID bundle, with
fresh trade-intent and original-source provenance supplied by the caller.
A wire-shaped result is NOT a signing permission or submit-ready packet:
separate signer, unique durable claim, manual approval, exchange reconciliation
and independent live stops are still MISSING.
"""
from dataclasses import dataclass
from decimal import Decimal
import re

from testnet_paper_review.offline_client_order_bundle import (
    build_offline_client_order_bundle
)
from testnet_paper_review.offline_order_guard import (
    TESTNET_ACCOUNT, TESTNET_ENDPOINT, HoldError
)

SDK_VERSION_REVIEWED = "0.24.0"
APPROVED_COIN = "SOL"


@dataclass(frozen=True)
class UnsignedSDKWireReview:
    account: str
    endpoint: str
    asset_id: int
    grouping: str
    action: dict
    plan_hash: str
    mode: str = "OFFLINE_WIRE_ENCODING_HOLD"

    @property
    def may_sign(self):
        return False

    @property
    def may_send(self):
        return False


def _asset_id(meta):
    if type(meta) is not dict or type(meta.get("universe")) is not list:
        raise HoldError("HOLD: unverified TESTNET perpetuals metadata")
    universe = meta["universe"]
    if len(universe) > 2000:
        raise HoldError("HOLD: oversized metadata")
    matches = [(i, asset) for i, asset in enumerate(universe)
               if type(asset) is dict and asset.get("name") == APPROVED_COIN]
    if len(matches) != 1:
        raise HoldError("HOLD: ambiguous SOL perp asset ID")
    idx, asset = matches[0]
    if type(asset.get("szDecimals")) is not int \
            or not 0 <= asset["szDecimals"] <= 5:
        raise HoldError("HOLD: unknown SOL size precision")
    if asset.get("isDelisted") is True:
        raise HoldError("HOLD: delisted SOL")
    return idx, asset["szDecimals"]


def compile_unsigned_sdk_wire(*, plan, intent, code_sha, now_s, meta):
    """Verify SDK encodes exactly three protected orders and client IDs."""
    if intent.account.lower() != TESTNET_ACCOUNT.lower() \
            or intent.endpoint != TESTNET_ENDPOINT:
        raise HoldError("HOLD: wrong owner or Mainnet")
    bundle = build_offline_client_order_bundle(
        plan=plan, intent=intent, code_sha=code_sha, now_s=now_s
    )
    if bundle.endpoint != TESTNET_ENDPOINT or bundle.account.lower() != TESTNET_ACCOUNT.lower() \
            or bundle.permits_submission or bundle.grouping != "normalTpsl":
        raise HoldError("HOLD: unapproved SDK bundle")
    asset, decimals = _asset_id(meta)
    try:
        from hyperliquid.utils.types import Cloid
        from hyperliquid.utils.signing import (
            order_request_to_order_wire, order_wires_to_order_action
        )
    except ImportError as exc:
        raise HoldError("HOLD: pinned SDK unavailable") from exc
    source = bundle.orders
    if type(source) is not tuple or len(source) != 3:
        raise HoldError("HOLD: must have entry + both protection orders")
    if len({row["cloid"] for row in source}) != 3:
        raise HoldError("HOLD: duplicate entry/protection identifiers")
    encoded = []
    for i, order in enumerate(source):
        if type(order) is not dict or set(order) != {
            "coin","is_buy","sz","limit_px","order_type","reduce_only","cloid"
        }:
            raise HoldError("HOLD: unsupported order SDK fields")
        if order["coin"] != APPROVED_COIN \
                or not re.fullmatch(r"0x[0-9a-f]{32}", order["cloid"]):
            raise HoldError("HOLD: foreign coin or malformed order ID")
        px = Decimal(order["limit_px"])
        size = Decimal(order["sz"])
        if px <= 0 or size <= 0:
            raise HoldError("HOLD: invalid price or size")
        if size.as_tuple().exponent < -decimals:
            raise HoldError("HOLD: size exceeds live SOL lot precision")
        # SDK rejects floats that would change at 8 wire decimals. Never
        # silently round or change an entry or an attached trigger.
        order_type = order["order_type"]
        if i:
            t = order_type["trigger"]
            sdk_type = {"trigger": {
                **t,"triggerPx":float(t["triggerPx"])
            }}
        else:
            sdk_type = {"limit":{"tif":"Ioc"}}
        sdk_order = {
            **order,"sz":float(size),"limit_px":float(px),
            "order_type":sdk_type,
            "cloid":Cloid.from_str(order["cloid"])
        }
        try:
            wire = order_request_to_order_wire(sdk_order,asset)
        except (TypeError,ValueError) as exc:
            raise HoldError("HOLD: Hyperliquid SDK rejected order wire") from exc
        if wire.get("a") != asset or wire.get("c") != order["cloid"] \
                or Decimal(wire["p"]) != px or Decimal(wire["s"]) != size:
            raise HoldError("HOLD: SDK encoding altered price/size/order ID")
        if i and Decimal(wire["t"]["trigger"]["triggerPx"]) != Decimal(order_type["trigger"]["triggerPx"]):
            raise HoldError("HOLD: SDK encoding altered protective trigger")
        encoded.append(wire)
    if [o["r"] for o in encoded] != [False,True,True] \
            or encoded[0]["t"] != {"limit":{"tif":"Ioc"}}:
        raise HoldError("HOLD: wrong IOC or reduce-only protection")
    action = order_wires_to_order_action(encoded,grouping="normalTpsl")
    if action.get("grouping") != "normalTpsl" or action.get("type") != "order" \
            or len(action.get("orders",[])) != 3:
        raise HoldError("HOLD: unexpected SDK group order shape")
    return UnsignedSDKWireReview(
        account=TESTNET_ACCOUNT,endpoint=TESTNET_ENDPOINT,
        asset_id=asset,grouping="normalTpsl",action=action,
        plan_hash=bundle.plan_hash
    )
