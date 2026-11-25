"""Staging-only: never release an ownership fence without two fresh checks."""
from staging_executor_gateway_contract import BOTS
from trusted_reconciler_worker_staging import reconcile_closed

def release_verified(info, address, rpc, *, coin, bot, token, clock):
    if not coin or bot not in BOTS or not token:
        return False
    params = dict(p_coin=coin, p_bot=bot, p_token=token,
                  p_exchange_flat=True, p_no_open_orders=True)
    first = reconcile_closed(info, address, coin=coin, clock=clock)
    if first.action != 'release_candidate':
        return False
    try:
        if rpc('mark_bot_position_closed', params) is not True:
            return False
    except Exception:
        return False
    second = reconcile_closed(info, address, coin=coin, clock=clock)
    if second.action != 'release_candidate':
        return False
    try:
        return rpc('release_closed_bot_position', params) is True
    except Exception:
        return False
