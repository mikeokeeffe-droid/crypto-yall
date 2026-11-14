# Hyperliquid SDK 0.24.0 close-order source review (offline)

Source: https://github.com/hyperliquid-dex/hyperliquid-python-sdk/blob/0.24.0/hyperliquid/exchange.py
Verified against the upstream `0.24.0` tag, file blob SHA `41a2f66b568451208770517d5afd58af724edded`.

## Confirmed source behavior

- `Exchange.market_close(coin, sz=None, ...)` queries `self.info.user_state(address, dex)["assetPositions"]`.
- Account selection uses wallet address, overridden by `account_address`, then by `vault_address`.
- It locates the requested coin, reads signed position size `szi`, and if `sz` is absent or falsy substitutes `abs(szi)`.
- It chooses the opposing order direction from the sign of `szi`, then calls `self.order(..., order_type={"limit":{"tif":"Ioc"}}, reduce_only=True, ...)`.
- This confirms the SDK **requests** reduce-only execution. It does not prove exchange acceptance, fill size, ownership, freshness, or close completion.
- The original Daily, Intraday, and Aggressive bots all call `exchange.market_close`; when their `close_size` is absent or nonpositive they call the unsized fallback.
- Their kill-switch checks exit before normal order dispatch, so automated closes do not run when that switch halts execution.

## Outstanding production safety decisions

1. Verify the effective account and vault identity and freshness of the position snapshot used for each close.
2. Ensure a bot cannot close another bot's shared-account position by relying solely on coin or stale local ownership.
3. Review the unsized fallback and oversized/stale explicit `sz` values; fail closed where ownership or size is uncertain.
4. Distinguish entry-disabled/protection-only operation from a hard kill switch; never silently change the existing switch semantics.
5. Require authenticated exchange receipts and reconciliation of partial fills, rejected orders and unknown outcomes.
6. Independently review and approve any proposed executor changes before deployment.

This document is analysis only. No live executor, SDK dependency, exchange, production database, or workflow is modified by this review.
