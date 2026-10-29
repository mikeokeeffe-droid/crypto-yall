# PR #38 — executor integration contract (review-only)

**Status: LIVE ENTRIES BLOCKED; NO-GO.** No live executor imports the staging
fence. The three `execute_trade()` functions now reject every non-close action
before sizing, leverage changes, or order submission. Close paths remain
independent. A staging-only WSGI-callable request handler now authenticates
each bot with its own key and restricted LOGIN and returns reservation/intent
results only. It starts no listener and is not wired to live executors; it does
not authorize orders or satisfy production integration requirements.

Do not merge, deploy, enable bots or place orders from this document.

## Verified entry call sites

| Bot | File | Entry dispatch |
| --- | --- | --- |
| Aggressive | `aggressive_executor.py` | `main()` around line 802 calls `execute_trade()`; `market_open()` around line 544 |
| Intraday | `intraday_executor.py` | `main()` around line 838 calls `execute_trade()`; `market_open()` around line 553 |
| Daily | `hyperliquid_executor.py` | `main()` around line 1278 calls `execute_trade()`; `market_open()` around line 490 |

These are code-review locations, not a guarantee that no other order-producing
path exists. Search all exchange order methods and alternate workflows before
implementation. The existing `pending_entry_claims` Gist state is local
recovery metadata, **not** a cross-bot atomic reservation.

## Staging request handler

`staging_executor_http_gateway.create_staging_executor_entry_app()` returns a
WSGI callable for `POST /staging/entry-claims`; it does not start a listener.
Clients send a Bearer JWT and exactly `{"bot","coin","action"}` as JSON. The
server supplies the three distinct signing keys, connection factories, and
restricted LOGIN mappings. Successful responses contain only the reservation
and intent claim booleans. There is no order-authorization result, exchange
client, or client-selected database credential or RPC name.

The database has a protected `bot_entry_executor_identities` map. PostgreSQL
reserve, intent-claim, and release RPCs bind their requested bot to
`session_user`, independently of the HTTP layer. The disposable PostgreSQL
test directly calls those RPCs through each bot LOGIN and verifies cross-bot
requests are denied. Privileged database administrators remain outside this
restricted-LOGIN boundary and must not be used by server request handling.

## Required live integration contract

1. An authenticated, dedicated **executor** database principal (distinct from
   reconciler and privileged service credentials) must atomically acquire a
   per-coin reservation and durable pending intent before any `market_open`.
   Reject absent/mismatched tokens, stale leases, DB outages and ambiguous
   responses. Never fall back to the old unguarded entry path.
2. Query exchange position and open-order evidence with bounded pagination and
   freshness checks. Unknown/partial/unavailable evidence blocks **entries**.
   Close and protective exit paths remain independent of entry-gate failures.
3. After submission, persist the exchange order identity and observed state.
   Network timeouts or unknown fills retain the durable fence; never release
   based only on an expired reservation or a failed local Gist write.
4. Only an independently authenticated reconciler using a separate restricted
   DB principal can confirm fills and release verified-flat owners. Never
   infer a safe release from a missing position in a single stale snapshot.
5. Add explicit offline feature gating and exhaustive order-method call-site
   coverage. A gate disabled or misconfigured in production must not silently
   permit an unprotected entry. Stage with disposable credentials and fake
   exchange clients before any separately approved canary.
6. Require independent security review of SQL ownership/grants, credential
   provisioning, authenticated gateway, rollback, three-bot concurrency,
   uncertain order recovery and audit logs.

## Acceptance evidence still missing

- Real executor runtime wiring and tests against their actual entry dispatch
  (the added offline tests extract the real `execute_trade()` function ASTs;
  they do not prove a live authenticated reservation integration).
- Deployed gateway identity-to-dedicated-login binding, key lifecycle and
  production grants inventory.
- Server hosting, staging credential provisioning, key rotation/revocation,
  TLS/network policy, audit logging, rate limiting, and operational monitoring.
- Full three-bot restart, pagination, partial fill and failure-injection E2E.
- Independent approval, explicit operator cutover permission and rollback.

**No production changes authorized. All three bots remain OFF.**
