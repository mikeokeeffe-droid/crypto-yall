# PR #38 — executor integration contract (review-only)

**Status: LIVE ENTRIES BLOCKED; NO-GO.** Each executor's real `execute_trade()`
dispatch accepts an optional, injected staging gateway callable. The default is
`None`; no network client or credentials are loaded by executor entrypoints. A
host-created client can use the staging-only HTTPS transport with an explicit
private destination allowlist and per-bot signing keys. If injected, the callable
may authenticate and claim a staging reservation/intent, but the executor
unconditionally returns `blocked` and contains no `market_open` or leverage
change path. The close/partial-close branch runs before the gateway and remains
independent. The WSGI gateway starts no listener and is not production wired.

Do not merge, deploy, enable bots or place orders from this document.

## Verified entry call sites

| Bot | File | Entry dispatch |
| --- | --- | --- |
| Aggressive | `aggressive_executor.py` | `main(entry_gateway=None)` injects the optional dependency into `execute_trade()` |
| Intraday | `intraday_executor.py` | `main(entry_gateway=None)` injects the optional dependency into `execute_trade()` |
| Daily | `hyperliquid_executor.py` | `main(entry_gateway=None)` injects the optional dependency into `execute_trade()` |

These dispatch functions now contain no market-open or leverage mutation call.
This only fences the reviewed `execute_trade()` path; search all alternate
order-producing workflows before any future integration. The existing
`pending_entry_claims` Gist state is local recovery metadata, **not** a
cross-bot atomic reservation.

The injected callable receives keyword arguments `bot`, `coin`, and `action`.
It must return literal `True` or exactly
`{"reservation_claimed": true, "intent_claimed": true}` only after validating
the authenticated gateway response. All other results and expected
authentication, reservation, intent, permission, and transport failures return
`blocked`. Even the exact success response sets only `staging_claimed`; it
never changes the executor's blocked status.

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

## Required production integration contract

1. Independently review and configure the HTTPS gateway client/host adapter
   with approved private destination addresses, staging CA trust, and
   bot-specific credentials. Production main entrypoints leave the callable
   unset. No successful staging claim authorizes an order in this milestone.
2. Before any separately approved live order path, atomically acquire a
   per-coin reservation and durable pending intent. Reject absent/mismatched
   tokens, stale leases, DB outages and ambiguous responses. Never fall back to
   an unguarded entry path.
3. Query exchange position and open-order evidence with bounded pagination and
   freshness checks. Unknown/partial/unavailable evidence blocks **entries**.
   Close and protective exit paths remain independent of entry-gate failures.
4. After a separately authorized order submission, persist the exchange order identity and observed state.
   Network timeouts or unknown fills retain the durable fence; never release
   based only on an expired reservation or a failed local Gist write.
5. Only an independently authenticated reconciler using a separate restricted
   DB principal can confirm fills and release verified-flat owners. Never
   infer a safe release from a missing position in a single stale snapshot.
6. Preserve the default-disabled callable injection and fail-closed behavior.
   Any future order authorization requires a separately reviewed feature gate,
   exhaustive alternate order-call coverage, and explicit approval.
7. Require independent security review of SQL ownership/grants, credential
   provisioning, authenticated gateway, rollback, three-bot concurrency,
   uncertain order recovery and audit logs.

## Acceptance evidence still missing

- A deployed identity-to-dedicated-LOGIN binding, verified startup permission
  gate, secret lifecycle, and audit/network controls. The HTTPS transport is
  implemented but has only mocked transport/DNS/TLS tests; no real staging
  secret manager, listener, or gateway endpoint is configured.
- Independent staging verification of the currently injected boundary using
  approved staging-only identities. Fake-service tests prove the executor
  dispatch cannot submit an order even after a successful claim, not that a
  deployed service is correctly authenticated or reachable.
- Deployed gateway identity-to-dedicated-login binding, key lifecycle and
  production grants inventory.
- Server hosting, staging credential provisioning, key rotation/revocation,
  TLS/network policy, audit logging, rate limiting, and operational monitoring.
- Full three-bot restart, pagination, partial fill and failure-injection E2E.
- Independent approval, explicit operator cutover permission and rollback.

**No production changes authorized. All three bots remain OFF.**
