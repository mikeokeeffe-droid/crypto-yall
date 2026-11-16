"""Non-executing capture of ORIGINAL legacy protective-close call shapes.

This is an OFFLINE review fixture. It can record a proposed explicit-size
close without signing, sending, opening an exchange client or authenticating
ownership. It does NOT return a successful exchange response: every
market_close() call raises ReviewOnlyMutationBlocked to prevent an original
executor from assuming a close succeeded. Unsized calls always fail closed.
No live bot may import or deploy this helper.
"""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from sender_review.legacy_order_capture_preview import ReviewOnlyMutationBlocked
from sender_review.worker_intent_fixture_builder_offline import (
    build_worker_intent_fixture_offline,
)


@dataclass
class LegacyProtectiveCloseCaptureOffline:
    fixture_bot: str
    fixture_nonce: str
    expected_coin: str
    fixture_position_side: str
    fixture_position_ref: str
    fixture_observed_position_size: str
    fixture_exit_reason: str
    # Parsed amount from the original explicit-size call; untrusted fixture.
    captured_close_size: str | None = None
    proposed_body: bytes | None = field(default=None, repr=False)
    calls: list = field(default_factory=list, repr=False)
    position_ownership_verified: bool = False
    exchange_state_verified: bool = False
    effective_reduce_only_verified: bool = False
    close_authorized: bool = False
    submit_authorized: bool = False
    signing_enabled: bool = False

    def market_close(self, coin, sz=None):
        """Record a bounded proposal ONLY, then always block execution.

        All scope/position fields are untrusted fixture values and must be
        checked independently by a future authenticated sender. In particular
        a requested reduce_only flag is not exchange-enforced protection.
        """
        self.calls.append("legacy_market_close_blocked")
        if (self.proposed_body is not None
                or type(coin) is not str or coin != self.expected_coin
                or type(sz) not in (int, float, Decimal)):
            raise ReviewOnlyMutationBlocked("unsized or mismatched close blocked")
        try:
            amount = Decimal(str(sz))
            if not amount.is_finite() or amount <= 0:
                raise ValueError("invalid close size")
            close_size = format(amount, "f")
        except (InvalidOperation, ValueError, OverflowError):
            raise ReviewOnlyMutationBlocked("invalid explicit close size") from None

        draft = build_worker_intent_fixture_offline(
            fixture_bot=self.fixture_bot,
            action="protective_close",
            coin=coin,
            side=self.fixture_position_side,
            request_nonce=self.fixture_nonce,
            close_size=close_size,
            observed_position_size=self.fixture_observed_position_size,
            position_ref=self.fixture_position_ref,
            exit_reason=self.fixture_exit_reason,
            reduce_only=True,
        )
        if draft.state != "fixture_body_review_only_HOLD":
            raise ReviewOnlyMutationBlocked("untrusted close fixture rejected")
        self.captured_close_size = close_size
        self.proposed_body = draft.fixture_body
        # Even a bounded and formatted fixture can never be a close ACK.
        raise ReviewOnlyMutationBlocked("NO_SEND_REVIEW_ONLY: close not executed")
