# PR #40 — Security gate review after offline IPC tests

**Decision: LIVE NO-GO. PR stays draft. Original bots unchanged.**

## Verified offline (not production proof)

- Disposable SQLite claims, restart journal and nonce replay ledger tests.
- Synthetic HMAC envelopes and worker-side verification; keys loaded from a
  permission-checked disposable credential file.
- Same-UID bypass tests intentionally show credential and journal exposure.
- Distinct-UID Linux permission audits for private files and Unix sockets.
- Kernel SO_PEERCRED test maps a distinct-UID socket client to an allowed bot.
- Empty/partial socket messages and listener restart fixture always HOLD.
- All offline CI checks passing at review baseline `befd025`.

## P0 blockers in implementation order

1. **Actual isolated coordinator service**: dedicated service UID, per-bot UIDs,
   private journal/replay store and signer, secure deployment configuration and
   lifecycle. Current fixtures are separate-process tests, not a deployable
   coordinator.
2. **Authenticated request protocol**: a real framed Unix socket server that
   verifies SO_PEERCRED for every connection, binds UID to bot/account/env,
   limits payload sizes/timeouts, and rejects malformed, spoofed or unsupported
   requests. Current socket tests do not execute authenticated journal claims
   over that socket.
3. **Atomic durable claim and dispatch state**: transactionally bind verified
   identity, request nonce, account/dex/coin claim and order intent; ensure
   retries/restarts never duplicate an order. Current tests cover pieces,
   not end-to-end behavior.
4. **Independent exchange reconciliation**: attribute orders, fills, partial
   fills, cancellations and manual/other-bot position changes; hold on stale,
   missing or ambiguous ownership evidence.
5. **Bounded reduce-only closes**: close only independently verified remaining
   bot-owned size, with explicit reduce-only, uncertain ACK and restart rules.
   Current fixtures deliberately never authorize dispatch or close.
6. **Staging/paper and operational review**: adverse network/restart tests,
   alerting, kill switch, permissions and secret rotation, rollback, operator
   approval and a separate explicit decision before any live change.

## Guardrails

Do not alter original live strategies/executors, merge PR #40, deploy, access
wallets, place live orders or modify production database. Offline CI passing
is necessary but not sufficient for deployment approval.

## Suggested next offline milestone

Implement a **disposable, framed Unix socket server** that obtains kernel peer
credentials inside the coordinator and maps the verified UID to a narrow
request_entry-only interface. Keep dispatch and close permanently HOLD, use
disposable files and tests, and require a separate UID in Linux CI. Only after
that can end-to-end journal/replay tests be meaningful.
