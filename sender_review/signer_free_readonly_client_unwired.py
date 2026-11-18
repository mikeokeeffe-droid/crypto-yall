"""Unwired, zero-network signer-free Hyperliquid /info client interface.

Review-only seam for a future authenticated *read-only* collector. The injected
transport is supplied exclusively by isolated tests; it is NOT a trusted
network channel, and this module is never imported by live bot workflows.
It cannot open an HTTP connection, acquire credentials, build an Exchange,
release a fence, approve an order, or prove where data came from.

Even a correctly parsed mock snapshot is HOLD. Never mistake the returned
legacy-compatible data shape for an account/position ownership attestation.
"""
from dataclasses import dataclass, field
import json
import re

from sender_review.signer_free_account_view_offline import (
    extract_signer_free_account_view_offline,
)

_ACCOUNT = re.compile(r"0x[0-9a-f]{40}\Z", re.ASCII)
_MAX_JSON_BYTES = 131072
_TESTNET = "testnet"


@dataclass(frozen=True)
class UnwiredSignerFreeReadOnlyView:
    state: str = "HOLD"
    reason: str = "untrusted offline input; no authenticated account reader"
    equity: float | None = None
    positions: dict = field(default_factory=dict)
    observed_read_types: tuple[str, ...] = ()
    fixture_parsed: bool = False
    additional_spot_read_needed: bool = False
    exchange_origin_authenticated: bool = False
    account_scope_verified: bool = False
    snapshot_freshness_verified: bool = False
    account_wide_history_verified: bool = False
    position_ownership_verified: bool = False
    trading_key_available: bool = False
    order_authorized: bool = False
    close_authorized: bool = False
    leverage_authorized: bool = False


def _unique_json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_json_constant(_):
    raise ValueError("invalid JSON constant")


def _strict_document(raw):
    # A future collector must independently enforce origin, TLS and response
    # bounds BEFORE passing bytes into this non-authorizing parser.
    if type(raw) is not bytes or not 0 < len(raw) <= _MAX_JSON_BYTES:
        raise ValueError("missing or oversized fixture response")
    doc = json.loads(
        raw.decode("utf-8"), object_pairs_hook=_unique_json_pairs,
        parse_constant=_reject_json_constant,
    )
    if type(doc) is not dict:
        raise ValueError("expected object")
    return doc


def inspect_unwired_signer_free_account_view(
    *, account, network, test_transport=None,
):
    """Apply exactly two allowlisted read shapes to MOCK response bytes.

    The test_transport callback receives a fresh dictionary containing only
    the fixed /info read type and the requested lower-case account. It is
    never obtained from environment, installed as a real Info client, or
    permitted to send orders. A caller-provided callback cannot attest a
    network source; use only offline fakes until independent host approval.
    """
    hold = UnwiredSignerFreeReadOnlyView()
    if (type(account) is not str or _ACCOUNT.fullmatch(account) is None
            or network != _TESTNET or not callable(test_transport)):
        return hold
    seen = []
    try:
        def read(read_type):
            if read_type not in ("clearinghouseState", "spotClearinghouseState"):
                raise ValueError("unsupported info read")
            seen.append(read_type)
            return _strict_document(test_transport({
                "type": read_type, "user": account,
            }))

        user_state = read("clearinghouseState")
        view = extract_signer_free_account_view_offline(user_state=user_state)
        if view.additional_spot_read_needed:
            spot = read("spotClearinghouseState")
            view = extract_signer_free_account_view_offline(
                user_state=user_state, spot_user_state=spot,
            )
        if not view.fixture_parsed:
            return UnwiredSignerFreeReadOnlyView(
                reason="invalid or incomplete untrusted info response",
                observed_read_types=tuple(seen),
                additional_spot_read_needed=view.additional_spot_read_needed,
            )
        return UnwiredSignerFreeReadOnlyView(
            state="PARSED_UNTRUSTED_INFO_FIXTURE_HOLD",
            reason="read-only legacy shape parsed; origin, freshness, history, "
                   "ownership and all execution rights remain unverified",
            equity=view.equity,
            positions=view.positions,
            observed_read_types=tuple(seen),
            fixture_parsed=True,
        )
    except Exception:
        # Fail closed on malformed bytes, transport errors and unexpected
        # fixture behavior. Never expose HTTP payloads or exception detail.
        return UnwiredSignerFreeReadOnlyView(
            reason="read-only fixture unavailable or invalid",
            observed_read_types=tuple(seen),
        )
