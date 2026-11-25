# Reconciler authentication and authorization boundary (design only)

**Status:** Staging-only implementation; no production deployment or credentials.

The `bot_reconciler NOLOGIN` database role is a *privilege grouping*, not an authenticated service account. Reconciler LOGINs receive no direct SELECT or DML on protected intent, reservation, ownership, or identity tables. They read and transition only through SECURITY DEFINER routines that bind `session_user` to one bot. PostgreSQL does not independently verify exchange evidence; only the authenticated receiver may invoke those routines after collecting server-side evidence.

The code now includes a callable-only WSGI receiving boundary in
`trusted_reconciler_receiver_staging.py`. It exposes fixed entry/release
operations, verifies the bot-specific reconciler JWT through the existing
dispatcher, and supplies only server-configured exchange clients, account
addresses, and dedicated restricted reconciler LOGINs. Request-supplied
database credentials, RPC names, or exchange-evidence booleans are rejected.
The low-level `authorized=True` service helper is not an authentication
boundary and must never be mounted directly. The receiver is not a listener or
deployed service.

## Proposed trust boundary

- A dedicated server-side reconciliation worker authenticates using a separately provisioned, narrowly scoped identity. Do not reuse the bots' Supabase `service_role` credential or expose credentials in GitHub Actions or client code.
- An allowlisted server-side API checks the worker identity, retrieves Hyperliquid order, fill, open-order and position evidence independently, and correlates it with coin, bot, reservation token and order ID. Reject missing, stale, inconsistent or paginated/incomplete evidence.
- Only after verification, invoke the trusted position mark/release routines through a per-bot isolated database principal. Prevent routine executors, anonymous users and authenticated client users from invoking release/intent-resolution RPCs.
- Treat duplicate delivery, process restarts, clock skew and RPC failures as fail-closed. Preserve unresolved intents and ownership until the same evidence can be safely rechecked.
- Log a non-secret audit record of evidence identifiers, decision, actor, timestamp and resulting state. Avoid storing API secrets or sensitive raw payloads in logs.
- Use a separate, restricted LOGIN per bot, each inheriting only the `bot_reconciler` capability role. Keep these principals server-controlled and never expose them to callers.

## Required tests before implementation approval

1. Reject unauthorized worker identities and leaked routine-executor credentials.
2. Reject contradictory or stale evidence, unverified partial fills, and incomplete open-order pagination.
3. Verify repeated reconciler calls are idempotent and cross-bot fencing remains in place until verified release.
4. Exercise database role separation, direct protected-table read/write denial, and bot-scoped SECURITY DEFINER reads using distinct reconciler LOGINs in disposable PostgreSQL.
5. Confirm production deployment requires separate manual approval, credentials provisioned outside repository, and rollback procedures.

This document is **not** evidence that the above protections are already implemented.
