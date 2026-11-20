"""Non-executing exchange-method adapter for REUSING legacy sizing logic.

Draft compatibility proof: the three existing execute_trade() functions can
call this object IN AN ISOLATED TEST without a Hyperliquid signer, wallet,
SDK or network. It NEVER opens/closes a trade or modifies leverage. It captures
syntactically reviewed ENTRY and explicitly parent-scoped Aggressive
PYRAMID proposals only, always HOLD. Legacy market_open does not carry
position ownership or pyramid context: the test harness must supply both
as UNTRUSTED out-of-band fixture metadata. It rejects every close, including
sized closes, because caller-provided ownership is insufficient.

DO NOT inject into a running executor, protection loop or workflow. No
production migration or permission follows from a successful capture.
"""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re

from sender_review.worker_intent_fixture_builder_offline import (
    build_worker_intent_fixture_offline,
)

_COIN = re.compile(r"[A-Z][A-Z0-9]{0,23}\Z", re.ASCII)
_NONCE = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_BOTS = frozenset(("daily", "intraday", "aggressive"))


class ReviewOnlyMutationBlocked(RuntimeError):
    """All exchange mutations are denied; never retry as a real order."""


@dataclass
class LegacyOrderCapturePreview:
    fixture_bot: str
    fixture_nonce: str
    # Mandatory, out-of-band context from the calling strategy decision.
    # A bare legacy market_open call does not distinguish pyramids.
    expected_action: str
    # Untrusted reference for an existing position in a synthetic review.
    # Required ONLY for Aggressive pyramids; never proves actual ownership.
    fixture_parent_position_ref: str | None = None
    proposed_body: bytes | None = field(default=None, repr=False)
    proposed_action: str | None = None
    observed_leverage: int | None = None
    observed_coin: str | None = None
    calls: list = field(default_factory=list, repr=False)
    signing_enabled: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    leverage_authorized: bool = False

    def __post_init__(self):
        if (type(self.fixture_bot) is not str
                or self.fixture_bot not in _BOTS
                or type(self.fixture_nonce) is not str
                or _NONCE.fullmatch(self.fixture_nonce) is None
                or self.expected_action not in (
                    "open_long", "open_short", "pyramid_long", "pyramid_short",
                )
                or (
                    self.expected_action.startswith("pyramid_")
                    and (self.fixture_bot != "aggressive"
                         or type(self.fixture_parent_position_ref) is not str
                         or _NONCE.fullmatch(self.fixture_parent_position_ref) is None)
                )
                or (
                    not self.expected_action.startswith("pyramid_")
                    and self.fixture_parent_position_ref is not None
                )):
            raise ValueError("invalid inert preview scope")

    def update_leverage(self, leverage, coin, is_cross):
        if (type(leverage) is not int or not 1 <= leverage <= 5
                or type(coin) is not str
                or _COIN.fullmatch(coin) is None
                or is_cross is not True
                or self.observed_leverage is not None):
            raise ReviewOnlyMutationBlocked("invalid leverage proposal")
        self.observed_leverage = leverage
        self.observed_coin = coin
        self.calls.append("reviewed_leverage_only")
        # No Hyperliquid API call, state mutation, account or keys exist.

    def market_open(self, coin, is_buy, size):
        if (self.proposed_body is not None
                or self.observed_leverage is None
                or type(coin) is not str or coin != self.observed_coin
                or type(is_buy) is not bool
                or type(size) not in (int, float, Decimal)):
            raise ReviewOnlyMutationBlocked("no executable entry permitted")
        try:
            quantity = Decimal(str(size))
            if not quantity.is_finite() or quantity <= 0:
                raise ReviewOnlyMutationBlocked("invalid size")
            size_text = format(quantity, "f")
        except (InvalidOperation, ValueError, OverflowError):
            raise ReviewOnlyMutationBlocked("invalid size") from None
        # market_open has no argument distinguishing pyramid from entry.
        # The expected strategy action is mandatory fixture-only context;
        # it MUST be established independently, never inferred from size.
        action = self.expected_action
        if is_buy != action.endswith("_long"):
            raise ReviewOnlyMutationBlocked("strategy action context mismatch")
        fields = {
            "rounded_size": size_text,
            "requested_leverage": self.observed_leverage,
        }
        if action.startswith("pyramid_"):
            fields["parent_position_ref"] = self.fixture_parent_position_ref
        preview = build_worker_intent_fixture_offline(
            fixture_bot=self.fixture_bot, action=action,
            coin=coin, side="long" if is_buy else "short",
            request_nonce=self.fixture_nonce, **fields,
        )
        if preview.state != "fixture_body_review_only_HOLD":
            raise ReviewOnlyMutationBlocked("invalid entry request")
        self.proposed_body = preview.fixture_body
        self.proposed_action = action
        self.calls.append("entry_proposal_only")
        # Non-ok acknowledgment prevents accidental claim of an exchange fill.
        return {"status": "error", "reason": "NO_SEND_REVIEW_ONLY"}

    def market_close(self, *args, **kwargs):
        # Legacy closes can lack explicit size or verified position ownership;
        # neither is safe to submit to a shared account.
        self.calls.append("close_blocked")
        raise ReviewOnlyMutationBlocked("close requires verified reduce-only sender")

