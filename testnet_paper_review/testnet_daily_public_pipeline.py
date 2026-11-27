"""Isolated Daily SOL Testnet readiness pipeline: public reads + review ONLY.

This is the final pre-trade *observer* seam, NOT an executable sender.
It uses a pinned Testnet public account reader, a pinned Testnet SOL market
reader, and the existing Daily strategy classification. No signer, key,
order post, secret, workflow dispatch or durable-state mutation exists here.

Twelve requests are deliberately bounded: account/orders/detailed orders,
public Spot USDC and userAbstraction mode, market meta/mids, then repeat
account/orders/detailed orders, Spot USDC and mode; changes are HOLD. The second
read detects account changes during market inspection. Any disagreement,
manual position, stale data, insufficient collateral, market metadata
ambiguity or missing NEW Daily signal is HOLD. Even a successful review
returns permits_submission=False.

No actor may treat a READINESS review as a live-order approval.
"""
from dataclasses import dataclass
from decimal import Decimal

from testnet_paper_review.daily_testnet_signal_adapter import (
    review_daily_signal, SignalReviewHold
)
from testnet_paper_review.testnet_daily_admission_gate import (
    assess, EXPECTED_ACCOUNT, EXPECTED_NETWORK
)
from testnet_paper_review.testnet_daily_readonly_preflight import (
    fetch_public_info, verify_consistent_order_views, ReadOnlyError
)
from testnet_paper_review.testnet_public_sol_market import (
    fetch_public_market, inspect_sol_market, MarketReadHold
)
from testnet_paper_review.testnet_spot_funds_probe import (
    fetch_spot, read_account_mode, SpotHold
)
from testnet_paper_review.offline_daily_bracket_plan import (
    compose_mock_bracket, BracketHold, OfflineBracketPlan
)

MAX_SPAN_S = 15
MAX_QUOTE_AGE_S = 10


class TestnetPipelineHold(RuntimeError):
    pass


@dataclass(frozen=True)
class TestnetReviewReceipt:
    status: str
    reason: str
    account: str
    symbol: str
    observed_positions: int
    observed_orders: int
    observed_market_price: str
    size_decimals: int
    candidate_bar: str
    planned_notional: str
    plan: OfflineBracketPlan

    @property
    def permits_submission(self):
        return False


def _account_snapshot(fetch_account):
    state = fetch_account("clearinghouseState")
    basic = fetch_account("openOrders")
    detailed = fetch_account("frontendOpenOrders")
    if type(state) is not dict or type(state.get("assetPositions")) is not list:
        raise TestnetPipelineHold("HOLD: missing independently observed positions")
    verify_consistent_order_views(basic, detailed)
    return state, basic, detailed


def review_testnet_daily_once(*, signal_fact, fetch_account=fetch_public_info,
                              fetch_market=fetch_public_market, clock=None,
                              notional_usdc="20", fetch_spot_state=fetch_spot,
                              fetch_mode=read_account_mode):
    """One public-only observation, with synthetic order-plan result.

    signal_fact is produced from exact Daily model evidence, not guessed.
    The independent reviewed model caller supplies the closed-bar proof.
    Injected fetchers in offline CI are *only fake* responses.
    """
    if clock is None:
        import time
        clock = lambda: int(time.time())
    if type(signal_fact) is not dict or set(signal_fact) != {
        "ticker", "last_signal", "prior_signal", "regime", "action",
        "bar_started_at_s", "observed_at_s", "legacy_leverage"
    }:
        raise TestnetPipelineHold("HOLD: missing/unreviewed Daily signal facts")
    start = clock()
    if type(start) is not int:
        raise TestnetPipelineHold("HOLD: invalid review clock")
    try:
        candidate = review_daily_signal(now_s=start, **signal_fact)
        state1, orders1, detailed1 = _account_snapshot(fetch_account)
        mode1 = fetch_mode()
        spot1 = fetch_spot_state() if mode1 == "unifiedAccount" else None
        market_start = clock()
        metadata = fetch_market("meta")
        mids = fetch_market("allMids")
        market_end = clock()
        market = inspect_sol_market(
            meta=metadata, mids=mids, start_s=market_start,
            finish_s=market_end
        )
        state2, orders2, detailed2 = _account_snapshot(fetch_account)
        mode2 = fetch_mode()
        spot2 = fetch_spot_state() if mode2 == "unifiedAccount" else None
        end = clock()
        if type(market_start) is not int or type(market_end) is not int \
                or type(end) is not int or not (
                    start <= market_start <= market_end <= end
                    and end - start <= MAX_SPAN_S
                    and end - market.observed_at_s <= MAX_QUOTE_AGE_S
                ):
            raise TestnetPipelineHold("HOLD: stale or inconsistent Testnet observations")
        # An observed account change in either snapshot is a hard stop. Do not
        # infer that another bot/manual position or order belongs to this bot.
        if (state1 != state2 or orders1 != orders2 or detailed1 != detailed2
                or mode1 != mode2 or spot1 != spot2):
            raise TestnetPipelineHold(
                "HOLD: Testnet account/orders changed during preflight"
            )
        if market.allows_trading or candidate.may_submit:
            raise TestnetPipelineHold("HOLD: public observation cannot grant trading")
        signal = candidate.admission_signal()
        verdict = assess(
            account=EXPECTED_ACCOUNT, network=EXPECTED_NETWORK,
            state=state2, open_orders=orders2,
            signal=signal, now_s=end, snapshot_at_s=start,
            notional_usdc=notional_usdc, leverage=1,
            account_mode=mode2, spot_state=spot2,
        )
        if verdict.status != "READY_FOR_REVIEW" or verdict.allows_order:
            raise TestnetPipelineHold("HOLD: " + verdict.reason)
        plan = compose_mock_bracket(
            account=EXPECTED_ACCOUNT, network=EXPECTED_NETWORK,
            state=state2, open_orders=orders2, signal=signal,
            now_s=end, snapshot_at_s=start, mid_price=market.mid_price,
            notional_usdc=notional_usdc, leverage=1,
            size_decimals=market.size_decimals,
            px_decimals=market.max_price_decimals,
            account_mode=mode2, spot_state=spot2,
        )
        if plan.permits_submission or plan.status != "HOLD_OFFLINE_REVIEW_ONLY":
            raise TestnetPipelineHold("HOLD: unexpected plan execution authority")
        return TestnetReviewReceipt(
            status="READY_FOR_HUMAN_REVIEW_ONLY",
            reason="HOLD: live orders disabled; signer/deployment still require security review",
            account=EXPECTED_ACCOUNT,
            symbol="SOL",
            observed_positions=len(state2["assetPositions"]),
            observed_orders=len(orders2),
            observed_market_price=market.mid_price,
            size_decimals=market.size_decimals,
            candidate_bar=candidate.bar_id,
            planned_notional=plan.effective_notional,
            plan=plan
        )
    except (SignalReviewHold, ReadOnlyError, MarketReadHold, SpotHold, BracketHold,
            OSError, TimeoutError, KeyError, TypeError, ValueError) as exc:
        raise TestnetPipelineHold("HOLD: Testnet public preflight failed closed") from exc
