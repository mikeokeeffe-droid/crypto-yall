"""Dependency-injected staging claim boundary for real executor dispatch."""
from collections.abc import Mapping

from staging_executor_gateway_contract import BOTS, ENTRY_ACTIONS


def staging_entry_dispatch_result(*, entry_gateway, bot, trade):
    """Request a staging claim, but never authorize a live order."""
    action = trade.get("action")
    coin = trade.get("hl_coin")
    if (type(bot) is not str or bot not in BOTS
            or type(action) is not str or action not in ENTRY_ACTIONS
            or type(coin) is not str or not coin.isascii()
            or not coin.isalnum() or coin != coin.upper()):
        return {
            **trade,
            "status": "blocked",
            "reason": "Invalid staging entry request",
            "staging_claimed": False,
        }
    if not callable(entry_gateway):
        return {
            **trade,
            "status": "blocked",
            "reason": "Staging gateway is not configured; live entry remains disabled",
            "staging_claimed": False,
        }

    try:
        response = entry_gateway(bot=bot, coin=coin, action=action)
    except (PermissionError, RuntimeError, TimeoutError, ConnectionError,
            OSError, ValueError) as error:
        return {
            **trade,
            "status": "blocked",
            "reason": (
                "Staging gateway failed closed "
                f"({type(error).__name__}); live entry remains disabled"
            ),
            "staging_claimed": False,
        }

    claimed = response is True or (
        isinstance(response, Mapping)
        and set(response) == {"reservation_claimed", "intent_claimed"}
        and response.get("reservation_claimed") is True
        and response.get("intent_claimed") is True
    )
    if not claimed:
        return {
            **trade,
            "status": "blocked",
            "reason": "Staging gateway did not confirm the reservation and intent",
            "staging_claimed": False,
        }

    return {
        **trade,
        "status": "blocked",
        "reason": (
            "Staging reservation and intent claimed; "
            "live order submission remains disabled"
        ),
        "staging_claimed": True,
    }
