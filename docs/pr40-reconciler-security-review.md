# PR #40 — independent reconciliation security review (NO-GO)

Review-only assessment of PR #40 against staging prototype PR #38, 2026-11-02.
This document is **not** approval to change production Supabase, GitHub Actions,
Hyperliquid permissions, live strategies, or database grants.

## Verified now

- The three original bot order-path tests and disposable PostgreSQL collision,
  restart, and restricted executor-LOGIN denial tests run on CI.
- Local `pending_entry_claims` block uncertain same-bot retries, including
  Aggressive pyramids. They are **not** a shared cross-bot atomic lock.
- A CI-only shared coordinator can reserve and persist an intent in one
  PostgreSQL transaction. Its database-specific implementation is explicitly
  disabled outside the disposable `safety_test` runner.
- `entry_reconciliation_review_offline.py` returns `hold` or
  `review_candidate` from **supplied synthetic-style evidence**. It does not
  authenticate Hyperliquid, check real account ownership, delete a claim or
  invoke a reconciler.
- PR #40 has **no separately authenticated reconciler LOGIN, trusted
  reconciler service, verified release transaction, or live order gate**.
  Neither the existing bots nor production Supabase use its new DB lock.

## Independent reconciler boundary: required vs. unverified

| Boundary | Required before staging promotion | Status in PR #40 |
| --- | --- | --- |
| Identity | Different dedicated reconciler LOGIN from all 3 executor LOGINs; bot-to-login mapping enforced by **database session identity**, not a caller-provided bot string | Missing |
| Least privilege | Executor may claim and record its own intent only; reconciler cannot submit entries; neither role gets broad table DML, inherited admin powers or unrestricted schema CREATE | Executor denial tested; reconciler not provisioned |
| Evidence | Independently fetched **authenticated** exchange order, bounded complete fills, open orders, position, account, and freshness; detect duplicates and conflicting responses | Only offline classifier tests, no authenticated reader |
| Intent linkage | DB row must match coin/bot/token/order id, requested size and submission timestamp; missing order ID after timeout stays fenced | Review-only checks; no database-linked trusted worker |
| Provenance | Snapshot account and capture identifiers must be verified from the trusted exchange client; **matching JSON fields alone are not proof** | Missing |
| Transaction | Separate restricted reconciler uses one audited, idempotent, fenced transaction to hand off filled ownership or release independently proven no-fill; stale requests cannot release a newer intent | Missing in PR #40 |
| Protection | All three entry paths (including pyramids) must fail closed on shared DB outage/ambiguous orders; protective closes remain independent | Not wired to actual order dispatch |
| Production isolation | No service_role / postgres keys in Actions bots; no staging SQL run on existing Supabase; staging credential provisioning, revocation, TLS, audit and rollback approved | Unverified |

## Specific design concern from staging PR #38

PR #38 contains useful staging-only prototypes:
`db/position_ownership_staging.sql`,
`db/trusted_reconciler_role_staging.sql`,
`trusted_reconciler_postgres_transport_staging.py`, and its extensive
disposable PostgreSQL tests. **Do not copy these wholesale into production.**

The SQL release routines accept caller-provided assertions such as
`p_zero_fills`, `p_exchange_flat`, and `p_no_open_orders`. PostgreSQL
cannot authenticate that exchange evidence from boolean arguments. The
independent worker **must** fetch and validate authoritative evidence first;
an authenticated account alone is not sufficient if it can falsely attest
to the booleans. The owner-handoff and release path also requires complete
rollback/identity/permission review and race tests.

The PR #40 CI-only `fence_token` is database-generated but is **not yet
enforced at a live exchange submission boundary**. A monotonically assigned
integer alone does not fence a stale process.

## Safe next implementation order (staging only)

1. Review PR #38's staging reconciler code and SQL with an independent
   reviewer; audit effective privileges (including PUBLIC defaults,
   SECURITY DEFINER search paths, inheritance and alternative RPC routes).
2. In **disposable** PostgreSQL, test an independently authenticated
   reconciler principal with no executor privileges. Include negative tests
   for bot impersonation, order mismatch, stale intent, conflicting fill,
   unknown timeouts, partial fills, pagination failures, and replay.
3. Test an injected read-only exchange-evidence provider using mocks, then
   an explicitly approved test-only account with bounded data reads.
   No orders, production API keys, or live data writes.
4. Prove a controlled reconciliation transaction retains the fence on every
   ambiguous outcome, and that filled ownership remains fenced until
   separately verified closure. Confirm protective closes never require
   the shared entry lock.
5. Only after independent review, design a separately approved, **disabled
   by default** staging connection to all three original executor entry paths.
   Do not enable live orders or merge a deliberately entry-blocking prototype.
6. Require explicit operator approval and a complete rollback/kill-switch
   plan before any live deployment or production-Supabase change.

## Release decision

**NO-GO.** Green CI tests demonstrate the tested offline/isolated properties,
not safety of real orders. PR #40 stays draft. No production migration,
Supabase credential provisioning, deployment or merge is authorized.
