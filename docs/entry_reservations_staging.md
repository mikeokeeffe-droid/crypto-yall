# Atomic entry reservation — staging proposal

This branch **does not change live executors, workflow schedules, leverage, or Gist state**. The SQL is an isolated proposal; do not apply to live Supabase yet.

## Why

All three bots share one Hyperliquid account. Their existing cross-bot lock checks already-open exchange positions, but two bots can simultaneously observe no position and submit conflicting orders. A database uniqueness constraint on `coin` and an atomic conditional UPSERT can serialize the entry intent.

## Safe integration requirements before live deployment

1. Confirm all three executors use the **same** reservation store. If a bot cannot reach the store, fail closed (do not submit entry).
2. Acquire the reservation **before** any external entry/pyramid order; use a unique UUID token per intent. Do not retry an ambiguous order blindly.
3. After acquiring, **re-read exchange positions** and check for an existing or pending entry. An exchange position from another bot must block the order.
4. Keep the reservation until order outcome and position ownership are reconciled. **Never release just because the HTTP request timed out**: the exchange may have filled.
5. Handle leases expiring while an order is unresolved; a TTL alone does **not** prevent duplicates after expiry. Use persisted intent/fill reconciliation and a fenced generation or durable claim before enabling live entry.
6. Preserve protection-only exit monitoring even when entry reservation infrastructure is unavailable. Avoid a shared global lock that blocks exits.
7. Run concurrency tests against disposable PostgreSQL with separate transactions, plus simulated API timeouts, fills, cancellations, retries and stale claims.
8. Validate Supabase RPC grants and CAS state revision safety. Roll out in protection-only / dry-run first, then one bot at a time only after explicit approval.

## Manual staging test

On disposable PostgreSQL only, execute `db/entry_reservations_staging.sql`, then `tests/entry_reservations_staging.sql`. The test rolls back its changes. **This test is not evidence of production safety or real concurrent correctness.**

## Current status

The SQL and smoke test are review artifacts. No live state migration, workflow activation, or exchange order is performed by this branch.
