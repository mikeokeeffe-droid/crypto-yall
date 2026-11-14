"""Disabled-by-design, CI-only signer-free original bot read bootstrap.

Builds a scoped synthetic read-only Info client and a non-executable V2
entry-review proposal. This is a replacement *interface prototype*, not a
replacement for original live get_client() or an authenticated runtime.
It has no trading client, signer, HTTP, socket, database or dispatch method.
A proposed leverage is NEVER evidence that exchange leverage was applied.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import re

from offline_signer_free_bot_view_ci import make_offline_signer_free_bot_view
from offline_leverage_bound_entry_draft_ci import OfflineLeverageDraft

_QUANTITY = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z", re.ASCII)


@dataclass(frozen=True)
class OfflineReadBootstrap:
    """Info-only startup plus one review-data builder, no order capability."""
    bot: str
    account: str
    environment: str
    info: object
    origin_authenticated: bool = False
    ownership_verified: bool = False
    submit_authorized: bool = False

    def draft_entry_review(self, *, trade, rounded_size, requested_leverage):
        """Build V2 review-only data or HOLD; never provide a send permission."""
        hold = OfflineLeverageDraft()
        if (type(requested_leverage) is not int
                or not 1 <= requested_leverage <= 5
                or type(rounded_size) is not str
                or _QUANTITY.fullmatch(rounded_size) is None):
            return hold
        try:
            amount = Decimal(rounded_size)
            if not amount.is_finite() or amount <= 0:
                return hold
            from offline_original_bot_intent_adapter import (
                prepare_signer_free_entry_handoff_offline,
            )
            request = prepare_signer_free_entry_handoff_offline(
                verified_bot=self.bot, trade=trade,
                rounded_size=rounded_size,
                pinned_environment=self.environment,
                pinned_account=self.account,
            )
            if (request.state != "request_only"
                    or request.submit_authorized
                    or type(request.request_json) is not str):
                return hold
            entry = json.loads(request.request_json)
            if (type(entry) is not dict
                    or set(entry) != {
                        "operation", "action", "side", "hl_coin", "rounded_size"
                    }
                    or entry["operation"] != "request_entry"
                    or entry["rounded_size"] != rounded_size):
                return hold
            preview = {
                "operation": "review_entry_leverage_v2",
                "action": entry["action"],
                "side": entry["side"],
                "hl_coin": entry["hl_coin"],
                "rounded_size": rounded_size,
                "requested_leverage": requested_leverage,
                "cross_margin_requested": True,
            }
            wire = json.dumps(preview, sort_keys=True, separators=(",", ":"))
            if len(wire.encode("utf-8")) > 1024:
                return hold
            return OfflineLeverageDraft(
                state="review_only",
                reason="synthetic review data only; exchange not contacted",
                review_json=wire,
            )
        except (ValueError, TypeError, InvalidOperation):
            return hold


def bootstrap_original_read_only_offline(
    *, verified_bot, pinned_environment, pinned_account, snapshot,
):
    """Return None unless a strictly scoped synthetic Info view is available."""
    view = make_offline_signer_free_bot_view(
        verified_bot=verified_bot, pinned_environment=pinned_environment,
        pinned_account=pinned_account, snapshot=snapshot,
    )
    if view is None:
        return None
    return OfflineReadBootstrap(
        bot=view.bot, account=view.account,
        environment=view.environment, info=view.info,
    )
