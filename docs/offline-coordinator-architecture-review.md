# Offline coordinator architecture review — 2026-11-10

**Decision: NO-GO for live trading.** This review covers only the draft PR #40
fixtures. It is not a production security sign-off.

## Existing boundaries

| Component | What is demonstrated | Why it is not production-ready |
| --- | --- | --- |
| `offline_atomic_coordinator_fixture.py` | One SQLite transaction for nonce, claim and fence; offline rollback/restart/concurrency tests | No authenticated caller boundary; filename-based SQLite open remains race-prone; no exchange outcome reconciliation |
| `offline_coordinator_listener_fixture.py` | Linux `SO_PEERCRED` allowlist, bounded one-request Unix listener, private file checks | Calls the **old two-database bridge**, not the atomic prototype; socket mode `0600` prevents other worker UIDs from connecting; accepts only one request |
| `offline_socket_journal_bridge_fixture.py` | Frame validation and UID-derived identity, nonce replay HOLD | Two independent SQLite commits, so not atomic; does not call the new atomic prototype |
| `offline_sender_restart_journal.py` / `offline_persistent_replay_ledger.py` | Durable independent offline test state | Must not be described as an atomic combined coordinator |
| Original Daily / Intraday / Aggressive bots | Unmodified by this prototype | No safe coordinator integration or deployment approval |

## Critical design decisions before any integration

1. **Service authority:** keep the coordinator a separate minimal process with
   no exchange signer initially. Workers must not write coordinator state.
   Distinct Linux UIDs, dedicated service UID and managed socket ACL/group
   policy must be proven with actual cross-UID connection tests.
2. **Persistence:** choose a protected state-service boundary that guarantees
   the SQLite file opened is the one validated. Pathname checks and
   `PRAGMA database_list` alone are not proof. Secure WAL/journal sidecars,
   durability, backups, restore and fencing-counter continuity need review.
3. **Protocol:** define authenticated, versioned, length-limited requests;
   stable principal identity; idempotency and error responses; deadlines;
   rate limiting; request ordering; restart behavior; explicit HOLD on
   missing, corrupt or ambiguous state. No worker-provided principal trust.
4. **Atomic state machine:** specify claim lifecycle transitions, ownership,
   lease/expiry policy (if any), recovery gates and a monotonic fence that
   cannot regress after restore. The current fixture only creates
   `reserved` claims; it does not implement recovery.
5. **Exchange evidence:** independently reconcile Hyperliquid orders, fills,
   positions, partial fills, manual trades and other bots before any release
   or retry. A database commit is **not** evidence that an exchange order
   was or was not executed.
6. **Close path:** separately design reduce-only exits, cross-bot ownership,
   quantity bounds and failure handling. Entry reservation does not authorize
   a close or any order.
7. **Operational gates:** adversarial staging, crash and network partitions,
   audit logs, incident stop procedure, rollback, independent review and
   explicit user approval are prerequisites to live enablement.

## Immediate offline milestones (in order)

- Add tests that **prove** the current listener still uses the two-file
  bridge; do not imply the atomic fixture is already wired to it.
- Define a new isolated **atomic-only** socket integration fixture; do not
  replace existing listeners or change live bots. Test real peer UID,
  malformed frames, replay, lost ACK, concurrent requests and restart.
- Choose and document the deployment-grade protected storage and IPC
  architecture, then independently review its threat model.
- Add evidence-driven reconciliation and close-path safety tests using
  disposable fixtures only.

**Explicit exclusions:** no secrets, API keys, wallets, production databases,
live exchange SDK calls, real orders, deployments, PR merge or live approval.
