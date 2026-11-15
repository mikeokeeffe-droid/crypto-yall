"""Pure, signer-free worker intent DRAFT builder for offline contract review.

A usable sender transport, authenticated bot worker, independent market read,
and exclusive signer DO NOT exist here. The caller supplies a fake bot
identity as *test metadata*, not proof of workload identity. Accepted output
is only a canonical, untrusted fixture body that must stay on HOLD.

Do not import this into current trading executors or deploy to a runner.
No environment reads, SDKs, sockets, DB operations, identity tokens, keys,
exchange calls or order authorization are permitted in this module.
"""
from dataclasses import dataclass
import json

from sender_review.proposed_intent_interfaces_offline import (
    inspect_proposed_intent_offline,
)

# Explicit allowlists prevent accidental caller-selected authority fields.
_FIELDS = {
    "open_long": frozenset(("rounded_size", "requested_leverage")),
    "open_short": frozenset(("rounded_size", "requested_leverage")),
    "pyramid_long": frozenset((
        "rounded_size", "requested_leverage", "parent_position_ref",
    )),
    "pyramid_short": frozenset((
        "rounded_size", "requested_leverage", "parent_position_ref",
    )),
    "protective_close": frozenset((
        "close_size", "observed_position_size", "position_ref",
        "exit_reason", "reduce_only",
    )),
    "request_leverage": frozenset((
        "requested_leverage", "parent_position_ref",
    )),
}


@dataclass(frozen=True)
class WorkerIntentDraft:
    state: str = "hold"
    reason: str = "no authenticated remote sender"
    fixture_body: bytes | None = None
    fixture_bot: str | None = None
    # These must NEVER be raised by a fixture builder.
    runtime_identity_authenticated: bool = False
    account_scope_verified: bool = False
    exchange_state_verified: bool = False
    request_authorized: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    leverage_authorized: bool = False
    signing_enabled: bool = False


def build_worker_intent_fixture_offline(
    *, fixture_bot, action, coin, side, request_nonce, **action_fields,
):
    """Construct strictly bounded canonical JSON for REVIEW ONLY.

    The fields represent untrusted caller observations and proposals.
    In particular, a protective close's observed_position_size is NOT
    an independently verified position, and a requested reduce_only=True
    is not an exchange-enforced reduce-only close.
    """
    hold = WorkerIntentDraft()
    if type(action) is not str or action not in _FIELDS:
        return hold
    if set(action_fields) != _FIELDS[action]:
        return hold
    if any(type(value) not in (str, int, bool) for value in action_fields.values()):
        return hold
    doc = {
        "version": 1,
        "action": action,
        "coin": coin,
        "side": side,
        "request_nonce": request_nonce,
        **action_fields,
    }
    try:
        body = json.dumps(
            doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, OverflowError, UnicodeError):
        return hold
    parsed = inspect_proposed_intent_offline(
        body=body, fixture_bot=fixture_bot,
    )
    if parsed.state != "parsed_review_only_HOLD":
        return hold
    return WorkerIntentDraft(
        state="fixture_body_review_only_HOLD",
        reason="canonical caller-supplied review fixture; NO authority",
        fixture_body=body,
        fixture_bot=fixture_bot,
    )
