"""Single-bot Intraday safety trial, offline and order-free.

This is deliberately independent of the live executor and exchange. It tests
the control-plane policy before enabling a real order submission path.
"""
from dataclasses import dataclass
from executor_integration_contract_staging import evaluate_executor_trade


@dataclass(frozen=True)
class TrialConfig:
    enabled_bot: str = "intraday"
    order_submission_enabled: bool = False


def simulate_trial_trade(store, *, bot: str, trade: dict,
                         position_flat: bool, no_open_orders: bool,
                         config: TrialConfig = TrialConfig()):
    if bot != config.enabled_bot:
        return {"decision": "bot_disabled", "order_submitted": False}
    if config.order_submission_enabled:
        raise ValueError("This trial harness must never enable order submission")
    result = evaluate_executor_trade(
        store, bot=bot, trade=trade, position_flat=position_flat,
        no_open_orders=no_open_orders,
    )
    return {"decision": result.decision, "order_submitted": False}
