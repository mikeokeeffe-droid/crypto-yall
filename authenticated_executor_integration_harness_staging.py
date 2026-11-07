"""Offline-only composition harness for authenticated executor entry staging."""
from dataclasses import dataclass
from typing import Any, Callable

from staging_executor_gateway_contract import ENTRY_ACTIONS
from trusted_executor_gateway_staging import StagedEntryClaim, stage_entry_claim


class _OfflineFakeExchange:
    is_offline_fake = True

    def __init__(self):
        self.calls = []

    def market_open(self, *args, **kwargs):
        self.calls.append(("market_open", args, kwargs))
        raise AssertionError("offline harness must never submit an entry order")

    def market_close(self, coin, sz=None):
        self.calls.append(("market_close", coin, sz))
        return {"status": "ok"}

    def update_leverage(self, *args, **kwargs):
        self.calls.append(("update_leverage", args, kwargs))
        raise AssertionError("offline harness must not change leverage")


@dataclass(frozen=True)
class OfflineHarnessResult:
    trade_result: dict
    claim: StagedEntryClaim | None
    exchange_calls: tuple
    failure: str | None = None
    live_order_submitted: bool = False


def execute_offline_authenticated_trade(
    *,
    execute_trade: Callable[..., dict],
    trade: dict,
    bot: str,
    jwt_token: str | None,
    signing_keys: dict,
    issuer: str,
    audience: str,
    rpc: Callable[..., bool] | None,
    now: int | None = None,
    capital: float = 1000.0,
    leverage: float = 1.0,
    info: Any = None,
) -> OfflineHarnessResult:
    """Compose the real gateway and executor against a fake exchange only."""
    exchange = _OfflineFakeExchange()
    action = trade.get("action")

    if action == "close":
        result = execute_trade(info, exchange, trade, capital, leverage)
        return OfflineHarnessResult(result, None, tuple(exchange.calls))

    if action not in ENTRY_ACTIONS:
        return OfflineHarnessResult(
            {**trade, "status": "blocked", "reason": "unsupported offline action"},
            None,
            tuple(exchange.calls),
            failure="PermissionError",
        )

    claims = []
    failures = []

    def authenticated_gateway(**request):
        try:
            claim = stage_entry_claim(
                jwt_token=jwt_token,
                bot=request["bot"],
                coin=request["coin"],
                action=request["action"],
                signing_keys=signing_keys,
                issuer=issuer,
                audience=audience,
                rpc=rpc,
                now=now,
            )
        except Exception as error:
            failures.append(type(error).__name__)
            raise
        claims.append(claim)
        return {
            "reservation_claimed": claim.claimed,
            "intent_claimed": claim.claimed,
        }

    result = execute_trade(
        info,
        exchange,
        trade,
        capital,
        leverage,
        entry_gateway=authenticated_gateway,
    )
    return OfflineHarnessResult(
        result,
        claims[0] if claims else None,
        tuple(exchange.calls),
        failure=failures[0] if failures else None,
    )