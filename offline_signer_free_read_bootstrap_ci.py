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


    def draft_original_candidate_review(
        self, *, candidate, rounded_size, requested_leverage,
    ):
        """Validate the original source-shaped candidate before V2 review.

        A bot candidate contains metadata (ticker, reason, rank) that must
        never flow to the coordinator as trusted scope or authorization.
        Projection requires its exact reviewed fields and returns only the
        three approved action/side/coin fields. This stays offline: it does
        not authenticate a process, apply leverage or send an order.
        """
        from offline_original_signal_projection_ci import (
            project_original_entry_candidate_offline,
        )
        projected = project_original_entry_candidate_offline(
            verified_bot=self.bot, candidate=candidate,
        )
        if (projected.state != "projected_review_only"
                or projected.submit_authorized
                or projected.ownership_verified
                or type(projected.trade_json) is not str):
            return OfflineLeverageDraft()
        try:
            trade = json.loads(projected.trade_json)
        except (TypeError, ValueError):
            return OfflineLeverageDraft()
        if type(trade) is not dict or set(trade) != {
            "action", "side", "hl_coin"
        }:
            return OfflineLeverageDraft()
        return self.draft_entry_review(
            trade=trade, rounded_size=rounded_size,
            requested_leverage=requested_leverage,
        )


    def draft_review_from_complete_decision_batch(
        self, *, decisions, selected_index, rounded_size, requested_leverage,
    ):
        """Offline-only check of a COMPLETE original decision cycle.

        One original decision cycle can include a close followed by an
        opposite-side new entry for the SAME coin. Since this synthetic
        prototype cannot prove that the close completed, refuse EVERY entry
        proposal in a cycle with a close, pyramid or unknown action. Also
        refuse duplicate coins or inconsistent/partial candidate shapes.

        This is NOT an atomic dispatch mechanism or exchange settlement
        proof. The harness must supply the entire original decision list;
        individual candidate review is not a security boundary on its own.
        """
        held = OfflineLeverageDraft()
        if (type(decisions) is not list or not 1 <= len(decisions) <= 3
                or type(selected_index) is not int
                or not 0 <= selected_index < len(decisions)):
            return held
        from offline_original_signal_projection_ci import (
            project_original_entry_candidate_offline,
        )
        coins = set()
        for candidate in decisions:
            projected = project_original_entry_candidate_offline(
                verified_bot=self.bot, candidate=candidate,
            )
            if (projected.state != "projected_review_only"
                    or projected.submit_authorized
                    or projected.ownership_verified
                    or type(projected.trade_json) is not str):
                return held
            try:
                reviewed = json.loads(projected.trade_json)
            except (ValueError, TypeError):
                return held
            if (type(reviewed) is not dict
                    or set(reviewed) != {"action", "side", "hl_coin"}
                    or reviewed["hl_coin"] in coins):
                return held
            coins.add(reviewed["hl_coin"])
        # The only permitted result here is NON-EXECUTABLE review data.
        return self.draft_original_candidate_review(
            candidate=decisions[selected_index],
            rounded_size=rounded_size,
            requested_leverage=requested_leverage,
        )


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
