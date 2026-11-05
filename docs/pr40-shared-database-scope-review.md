# PR #40 — shared entry database scope and permissions (offline review)

**Status: draft / CI-only / no production approval.** Never apply the disposable SQL to production or connect the original three bots to it without independent approval and testing.

## Existing concurrency protections

- Disposable PostgreSQL uses one durable unresolved intent per `coin`, enforced by a primary key.
- Reservation and intent creation take the same per-coin advisory transaction lock.
- Separate bot PostgreSQL logins are mapped by `session_user` rather than trusting a caller-provided bot label.
- An unresolved intent blocks another entry even if the short reservation expires.
- A database-generated fencing sequence and exact compare-and-swap tests reject stale handoffs.
- Existing CI tests exercise competing bot processes, failed claims, restarts and denied resolve/update privileges.

## Changes in this draft review

The disposable `bot_entry_executor_trial` role previously had blanket `SELECT` on `bot_entry_intents`. This exposed other bots' order-claim metadata, including their fencing tokens and UUIDs.

In **CI-only** `db/restricted_entry_logins_ci_only.sql`, that broad table grant has been removed. A `SECURITY DEFINER` function `read_bot_entry_claim_proof(coin, bot, token)` now checks that `session_user` maps to the exact requested bot; the caller must supply the exact coin and token; only that one row is returned. No table writes, resolving, exchange connection or production permissions were added. The isolated Python coordinator reads its proof through this narrowly scoped RPC, and the CI regression tests check direct `SELECT` denial and cross-bot proof denial.

The function is **not** proof of exchange position ownership. It verifies only that a matching durable claim is visible to a particular database login inside the disposable test database.

## Remaining production blockers

1. **Account scoping:** A reservation keyed only by `coin` cannot express multiple effective Hyperliquid accounts, vaults or perp DEXes; the current CI model is one logical account/default DEX. Do not deploy it unchanged to a multi-account setting. Future keys must include independently configured `environment + effective_account + dex + coin` (or a reviewed equivalent), with strict canonicalization and privilege isolation.
2. **Durable order intent:** The CI coordinator stores bot, coin, action and request UUID in separate contract paths but its SQL intent row does not yet persist all intended account, direction, size and order-submission evidence in one authenticated record. That gap must be fixed before any live order boundary.
3. **Claim release:** Administrative deletes and the example resolve function do not authenticate account-level exchange reconciliation. No live reconciler, release permission model, crash recovery or audit proof exists.
4. **Fencing:** The in-memory/CI fencing token is not enforced by any Hyperliquid order adapter. Reservation TTL alone must not release an unresolved order.
5. **Privilege hardening:** The SQL uses `SECURITY DEFINER` after a restricted CI-only grant setup; production requires dedicated schema ownership, function-owner isolation, a complete privilege audit, immutability of identities and tested migration/rollback.
6. **Race and netting:** Any manual orders or competing agents can alter account positions outside these tables. An independent account-wide read-only exchange collector and reconciler remain required.
7. **No live changes:** All checks here are based on a throwaway `safety_test` PostgreSQL container. They do not establish correctness against Supabase production, nor authorize automatic exchange closes.

**Decision: NO-GO.** Keep PR #40 in draft and original three executors unchanged.
