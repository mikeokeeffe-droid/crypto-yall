"""CI ONLY: non-signing sink for source-extracted original execute_trade().

This is a diagnostic seam, NOT a usable exchange client or production bot
adapter. Every mutation returns offline HOLD and never places an order.
Fresh entries can produce a request-only preview after original size rounding,
but cannot submit or authorize it. Pyramids, closes and leverage stay HOLD.
No network, database, SDK, secrets, filesystem or live executor imports.
"""
from decimal import Decimal, InvalidOperation

from offline_three_bot_mutation_review_ci import (
    OfflineMutationReview,
    review_original_bot_mutation_offline,
)

_HOLD_ACK = {"status": "offline_hold", "response": {}}


class OfflineOriginalExecutorMutationSink:
    """Capture calls of the actual isolated executor function, never execute."""

    def __init__(self, *, bot, trade, environment, account):
        self.bot = bot
        self.trade = dict(trade)
        self.environment = environment
        self.account = account
        self.events = []
        self.last_review = OfflineMutationReview()

    def _review(self, action, rounded_size, **additional):
        proposal = {
            "action": action,
            "hl_coin": self.trade.get("hl_coin"),
            "side": ("short" if action.endswith("_short") else "long"),
            **additional,
        }
        return review_original_bot_mutation_offline(
            verified_bot=self.bot, trade=proposal,
            rounded_size=rounded_size,
            pinned_environment=self.environment,
            pinned_account=self.account,
        )

    def update_leverage(self, leverage, coin, cross):
        # Original executors call this before opening; it must NOT be a
        # separately executable mutation on the bot side.
        self.events.append(("leverage_hold", coin, leverage, cross))
        self.last_review = self._review("update_leverage", "0")
        return None

    def market_open(self, coin, is_buy, size):
        # Match the reviewed original trade action and only preview its
        # already-rounded quantity. A signal is NOT trade authorization.
        action = self.trade.get("action")
        if (type(coin) is not str
                or coin != self.trade.get("hl_coin")
                or type(is_buy) is not bool
                or type(size) not in (float, int)):
            self.last_review = OfflineMutationReview(
                reason="invalid original exchange call")
            self.events.append(("entry_hold", None))
            return dict(_HOLD_ACK)
        try:
            value = Decimal(str(size))
            rounded = format(value, "f") if value.is_finite() else ""
        except (InvalidOperation, ValueError):
            rounded = ""
        expected_buy = action in ("open_long", "pyramid_long")
        if action not in ("open_long", "open_short", "pyramid_long",
                          "pyramid_short") or is_buy != expected_buy:
            self.last_review = OfflineMutationReview(
                reason="original trade action and order direction mismatch")
        else:
            self.last_review = self._review(action, rounded)
        self.events.append((
            "entry_request_only" if self.last_review.state == "request_only"
            else "entry_hold",
            rounded,
        ))
        return dict(_HOLD_ACK)

    def market_close(self, coin, sz=None):
        # The original unsized fallback calls market_close(coin); it must
        # NEVER infer account size or obtain an authorized close here.
        self.last_review = self._review(
            "close", "0", close_size=(str(sz) if sz is not None else None),
        )
        self.events.append(("close_hold", coin, sz))
        return dict(_HOLD_ACK)
