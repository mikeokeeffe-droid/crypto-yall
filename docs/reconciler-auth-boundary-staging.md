# Reconciler authentication and authorization boundary (design only)

**Status:** Staging proposal; no production deployment or credentials.

The `bot_reconciler NOLOGIN` database role is a *privilege grouping*, not an authenticated service account. The current SQL uses caller-supplied boolean assertions for exchange-flat and no-open-orders. Those flags are not independently verified by PostgreSQL.

## Proposed trust boundary

- A dedicated server-side reconciliation worker authenticates using a separately provisioned, narrowly scoped identity. Do not reuse the bots' Supabase `service_role` credential or expose credentials in GitHub Actions or client code.
- An allowlisted server-side API checks the worker identity, retrieves Hyperliquid order, fill, open-order and position evidence independently, and correlates it with coin, bot, reservation token and order ID. Reject missing, stale, inconsistent or paginated/incomplete evidence.
- Only after verification, invoke the trusted position mark/release routines through an isolated database principal. Prevent routine executors, anonymous users and authenticated client users from invoking release/intent-resolution RPCs.
- Treat duplicate delivery, process restarts, clock skew and RPC failures as fail-closed. Preserve unresolved intents and ownership until the same evidence can be safely rechecked.
- Log a non-secret audit record of evidence identifiers, decision, actor, timestamp and resulting state. Avoid storing API secrets or sensitive raw payloads in logs.
- Prefer a non-login database role bound to an explicitly authenticated server-side gateway, not a database login shared by all bots.

## Required tests before implementation approval

1. Reject unauthorized worker identities and leaked routine-executor credentials.
2. Reject contradictory or stale evidence, unverified partial fills, and incomplete open-order pagination.
3. Verify repeated reconciler calls are idempotent and cross-bot fencing remains in place until verified release.
4. Exercise database role separation under `SET ROLE` in disposable PostgreSQL.
5. Confirm production deployment requires separate manual approval, credentials provisioned outside repository, and rollback procedures.

This document is **not** evidence that the above protections are already implemented.
