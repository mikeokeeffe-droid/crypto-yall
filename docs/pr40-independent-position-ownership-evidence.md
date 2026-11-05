# PR #40 — independent position ownership evidence (offline design)

**Status: DRAFT / LIVE NO-GO.** No live exchange calls, order execution, credentials or changes to the three original bot executors.

## Why a matching position is not proof of ownership

Hyperliquid positions are account-level net exposure, not independently owned by a named bot. A matching account, coin and side, or a stored token/CLOID, cannot prove that Daily, Intraday or Aggressive exclusively owns a position. Manual orders, partial fills, cross-bot netting and external intervention can change that exposure.

## Minimum evidence before any bounded close may be considered

1. **Authenticated requester:** coordinator independently verifies the workload identity and its permitted account, environment and bot; caller-supplied `bot` is never authority.
2. **Durable coordinator intent:** immutable scoped entry intent, fencing, client-order identifier and complete journal history are available without gaps.
3. **Exchange-verified provenance:** independently fetch the exact account's order statuses, fills and relevant cancellations; correlate to the coordinator intent and prove which orders actually executed. Local logs or CLOID alone are insufficient.
4. **Current position reconciliation:** independently fetch fresh account-level position, side and size, and reconcile every relevant fill, manual trade and competing-bot action since the attributable entry. Require no unexplained net exposure.
5. **Conservative close bound:** requested reduction cannot exceed independently attributable remaining exposure or current account position. Use explicit size, correct reduce-only semantics, and exact account/coin/side; never an unbounded `market_close(coin)`.
6. **Time-of-check protection:** serialize all bot and manual exposure-changing actions through the coordinator, revalidate immediately before submission and retain fencing/idempotency. External/manual access that bypasses this coordination invalidates exclusive ownership assumptions.
7. **Ambiguity handling:** incomplete/stale history, netted cross-bot positions, unexpected account trades, unknown/manual exposure, inconsistent quantities, exchange outage or missing journal means **hold for review**; never guess or auto-close.

## Offline tests to implement

- Exact matching coin/side but another bot's entry: hold.
- Manual or unknown intervening fill: hold.
- Missing or stale fills/order status: hold.
- Partial fills, cancellations, reductions and position netting: never exceed attributable remaining size.
- Requested close size larger than attributable remaining exposure: hold.
- Exchange position smaller or opposite to claimed exposure: hold.
- Concurrent close requests and repeated/ambiguous acknowledgements: at most one bounded intent, no blind retries.
- Lost coordinator history, stale fencing or cross-account CLOID replay: hold.

## Unresolved production blockers

The offline coordinator fixture currently rejects **all** dispatch and close requests, so these checks cannot yet demonstrate safe *positive* close authorisation. A separate reconciliation engine and actual process/DB/exchange credential isolation are required before any production decision. **Live deployment remains NO-GO.**
