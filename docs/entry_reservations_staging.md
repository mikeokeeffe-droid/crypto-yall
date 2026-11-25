# Atomic entry reservation — staging proposal

This branch **does not change live executors, workflow schedules, leverage, or Gist state**. The SQL is an isolated proposal; do not apply to live Supabase yet.

## Why

All three bots share one Hyperliquid account. Their existing cross-bot lock checks already-open exchange positions, but two bots can simultaneously observe no position and submit conflicting orders. A database uniqueness constraint on `coin` and an atomic conditional UPSERT can serialize the entry intent.

## Safe integration requirements before live deployment

1. Confirm all three executors use the **same** reservation store. If a bot cannot reach the store, fail closed (do not submit entry).
2. Maintain exactly one protected `bot_entry_executor_identities` row per bot, mapping each bot to its own restricted PostgreSQL LOGIN. The reserve, intent-claim, and release RPCs compare this mapping with PostgreSQL `session_user`; an HTTP gateway or caller-supplied bot value cannot override the database identity. Do not map shared or privileged service accounts. Full database superusers remain trusted administrators and must never be used by the gateway.
3. Acquire the reservation **before** any external entry/pyramid order; use a unique UUID token per intent. Do not retry an ambiguous order blindly.
4. After acquiring, **re-read exchange positions** and check for an existing or pending entry. An exchange position from another bot must block the order.
5. Keep the reservation until order outcome and position ownership are reconciled. **Never release just because the HTTP request timed out**: the exchange may have filled.
6. Handle leases expiring while an order is unresolved; a TTL alone does **not** prevent duplicates after expiry. Use persisted intent/fill reconciliation and a fenced generation or durable claim before enabling live entry.
7. Preserve protection-only exit monitoring even when entry reservation infrastructure is unavailable. Avoid a shared global lock that blocks exits.
8. Run concurrency tests against disposable PostgreSQL with separate transactions, plus simulated API timeouts, fills, cancellations, retries and stale claims. Include direct-RPC cross-bot denial tests using each mapped LOGIN, bypassing the HTTP gateway.
9. Validate Supabase RPC grants and CAS state revision safety. Roll out in protection-only / dry-run first, then one bot at a time only after explicit approval.

## Manual staging test

On disposable PostgreSQL only, execute `db/entry_reservations_staging.sql`,
provision three distinct restricted LOGIN roles with synthetic credentials,
grant the trial RPC capability role, and map each LOGIN exactly once:

```sql
insert into public.bot_entry_executor_identities (bot, db_login) values
  ('aggressive', 'staging_aggressive_login'),
  ('intraday', 'staging_intraday_login'),
  ('daily', 'staging_daily_login');
```

Run `db/entry_reservation_identity_preflight_staging.sql` before testing. It
requires all three mapped roles to be restricted LOGIN members, rejects
unmapped executor LOGINs and extra role inheritance, and checks least-privilege
RPC/table grants. Then run the HTTP and direct-RPC PostgreSQL integration
tests. Never put database passwords in this mapping or in SQL files.
`tests/entry_reservations_staging.sql` rolls its transaction back.
**Passing disposable tests is not evidence of production safety or real
concurrent correctness.**

## Current status

The SQL and smoke test are review artifacts. No live state migration, workflow activation, or exchange order is performed by this branch.

For the staged deployment controls and remaining prerequisites, see the
[PR #38 staging deployment-readiness runbook](pr38-staging-deployment-runbook.md)
and its [non-runnable configuration checklist](templates/pr38-staging-gateway-config.example.yaml).
