"""CI-only V2 leverage-bound review draft: NOT a coordinator request.

The current V1 socket protocol carries size but NOT desired leverage.
This review-only draft is deliberately *incompatible* with that protocol
(operation='review_entry_leverage_v2'). It must never be sent as an order.
A future separately privileged sender must independently validate leverage,
margin mode, collateral, account state, fencing and risk before any dispatch.

No SDK, network, exchange, DB, credentials, live executors or order authority.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json

from offline_original_executor_mutation_sink_ci import (
    OfflineOriginalExecutorMutationSink,
)


@dataclass(frozen=True)
class OfflineLeverageDraft:
    state: str = "hold"
    reason: str = "leverage-bound intent not reviewed"
    review_json: str | None = None
    submit_authorized: bool = False
    leverage_applied: bool = False


class OfflineLeverageBoundEntrySink(OfflineOriginalExecutorMutationSink):
    """Inspect original update_leverage -> market_open sequence, no execution."""

    def __init__(self, *, bot, trade, environment, account):
        super().__init__(
            bot=bot, trade=trade, environment=environment, account=account,
        )
        self.leverage_attempts = 0
        self.requested_leverage = None
        self.cross_margin_requested = None
        self.last_draft = OfflineLeverageDraft()

    def update_leverage(self, leverage, coin, cross):
        # A method call is NOT exchange acknowledgement or successful leverage
        # change. Record the desired value only, including duplicate attempts.
        self.leverage_attempts += 1
        # Clear a previously observed proposal BEFORE calling the underlying
        # non-signing sink. If that operation throws, the original executor
        # catches its error and continues toward market_open. Never retain a
        # 'review_only' size+leverage draft after that failed call.
        self.requested_leverage = None
        self.cross_margin_requested = None
        result = super().update_leverage(leverage, coin, cross)
        if (self.leverage_attempts == 1
                and type(leverage) is int and 1 <= leverage <= 100
                and type(coin) is str and coin == self.trade.get("hl_coin")
                and cross is True):
            self.requested_leverage = leverage
            self.cross_margin_requested = True
        # The non-signing sink returning does NOT verify Hyperliquid leverage
        # application. The V2 payload stays non-executable review-only.
        return result

    def market_open(self, coin, is_buy, size):
        response = super().market_open(coin, is_buy, size)
        self.last_draft = OfflineLeverageDraft()
        if (self.last_review.state != "request_only"
                or self.last_review.submit_authorized
                or type(self.last_review.request_json) is not str
                or self.leverage_attempts != 1
                or self.requested_leverage is None
                or self.cross_margin_requested is not True):
            self.last_draft = OfflineLeverageDraft(
                reason="missing, repeated or unreviewed leverage proposal",
            )
            return response
        try:
            # Validate a canonical, strictly shaped request-only V1 preview,
            # then add the missing leverage information as review-only V2.
            v1 = json.loads(self.last_review.request_json)
            if (type(v1) is not dict
                    or set(v1) != {
                        "operation", "action", "side", "hl_coin", "rounded_size"
                    } or v1["operation"] != "request_entry"
                    or v1["hl_coin"] != coin
                    or v1["action"] not in ("open_long", "open_short")
                    or v1["side"] != ("long" if is_buy else "short")
                    or type(v1["rounded_size"]) is not str):
                return response
            size_decimal = Decimal(v1["rounded_size"])
            if not size_decimal.is_finite() or size_decimal <= 0:
                return response
        except (ValueError, TypeError, InvalidOperation):
            return response
        payload = {
            "operation": "review_entry_leverage_v2",
            "action": v1["action"],
            "side": v1["side"],
            "hl_coin": coin,
            "rounded_size": v1["rounded_size"],
            "requested_leverage": self.requested_leverage,
            "cross_margin_requested": True,
            # Deliberately exclude identity, signing, exchange order IDs,
            # and any false claim that leverage was applied.
        }
        wire = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        if len(wire.encode("utf-8")) > 1024:
            return response
        self.last_draft = OfflineLeverageDraft(
            state="review_only",
            reason="desired size and leverage captured; no order permission",
            review_json=wire,
        )
        return response

    def market_close(self, coin, sz=None):
        self.last_draft = OfflineLeverageDraft(
            reason="protective close requires separate bounded ownership review",
        )
        return super().market_close(coin, sz=sz)
