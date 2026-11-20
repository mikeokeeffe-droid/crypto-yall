# PR #40 — isolated shared-sender prototype implementation specification

**Draft only, 5 Nov 2026. NO-GO.** This is a build-ready *offline/disposable* implementation plan, not a live sender, order-placement approval, or migration. The three original bot strategies and executors must remain unchanged.

## Scope and exclusions

Build a separate prototype package (e.g. `prototype_sender_ci/`) with **no Hyperliquid SDK import, signing key, outbound HTTP, production Supabase credentials, or live workflow entry point**. It accepts immutable synthetic intents, simulates exchange outcomes with a deterministic fake, and stores state only in disposable PostgreSQL CI. No API endpoint or command that can send a real order is permitted. Its tests must not depend on a production account.

## Proposed modules

| Module | Role | Interface contract |
| --- | --- | --- |
| `intent_store` | Atomic scope admission, bot identity, immutable request and CLOID | `reserve(identity, scope, side, size, request_id) -> accepted/blocked` |
| `dispatch_journal` | Durable send attempt marker and audit events | `mark_unknown(intent_token, fence) -> journal_seq` with transaction commit before any fake dispatch |
| `serialized_dispatcher` | Single consumer for each account/DEX/coin | `simulate_once(intent_token, fence, fake_exchange) -> observed/hold`; never a real SDK call |
| `fake_exchange` | Deterministic accept, partial fill, timeout, delayed response and crash cases | In-memory order ID and fill fixtures only |
| `evidence_collector_stub` | Records synthetic response with explicit provenance=fixture | `capture(scope, cloid, oid, fills, position) -> fixture_ref` |
| `reconciliation_review` | Read-only checks of claim, journal, synthetic exchange history and account position | `review(scope, token, fence, captures) -> HOLD + reasons` |
| `offline_test_harness` | Concurrency, restart and fault injection | Two workers, deterministic barriers and disposable DB assertions |

No component may emit `submit_authorized=true`, call a trading endpoint, release an ambiguous claim, or silently mark ownership verified.

## Disposable database tables and access separation

Create new **CI-only** tables under the disposable `safety_test` database, separate from existing `ci_scoped_entry_claims` tests until reviewed:

- `ci_sender_intents`: exact `environment/effective_account/dex/coin` scope, authenticated bot login, UUID token, monotonic fence, opaque unique 16-byte CLOID, decimal size, direction, state, creation time; immutable after creation.
- `ci_sender_dispatch_attempts`: append-only attempt ID, intent token/fence, recorded timestamp, state `dispatch_unknown`, unique attempted-intent constraint. Record **before** fake dispatch; no second attempt even after crash.
- `ci_sender_observations`: append-only synthetic order status, OID, fill IDs, timestamps and provenance `fixture`; never a trusted exchange record.
- `ci_sender_audit_events`: append-only creation, attempt, fake observation and review events; correlate with intent token/fence.
- Dedicated bot roles may reserve only their own approved account scope; only a separate disposable sender role may mark dispatch attempt; collector role may append observations; reviewer role may read. No table update/delete grants to bot roles.

Use transactionally enforced unique `(environment,effective_account,dex,coin)` pending claim; an ambiguous attempt remains reserved forever unless a separately tested, operator-approved offline release mechanism is later designed. No TTL-based reuse. Test that a denied/failed insert cannot leave an orphaned claim or journal row.

## Prototype state machine

```text
ABSENT
  -> RESERVED (immutable intent, CLOID and fence committed)
  -> PREPARED (sender verifies scope, bot and current fence)
  -> DISPATCH_UNKNOWN (journal committed BEFORE fake send)
  -> OBSERVED_UNVERIFIED (synthetic response, still HOLD)

Any exception, timeout, crash, stale fence, mismatch or missing evidence:
  -> HOLD (reservation retained; no automatic retry/release)
```

**No transition to `owned`, `released` or `approved_close` in the prototype.** A simulated successful fill remains unverified by design.

## Required fault-injection tests

1. Three bot logins concurrently reserve SOL on one account: exactly one wins; other two cannot reach fake dispatch.
2. Same coin on two approved accounts: independent reservations; no cross-account reads.
3. Stale worker A pauses after reading fence; B tries to claim: B blocked while A is potentially in flight.
4. Crash before `dispatch_unknown` commit: no fake send; claim stays reserved.
5. Crash after `dispatch_unknown` commit but before fake send: no automatic replay or release.
6. Fake exchange accepts order but loses reply: exactly one fake dispatch attempt; later restart HOLD.
7. Partial fill, duplicate OID/TID, same-side manual fill, opposite-side netting: HOLD.
8. Missing fill window, 2,000-page boundary, 10,000-history retention, API clock mismatch: HOLD.
9. Bot impersonation, wrong environment, wrong account, stale fence, wrong CLOID: rejected.
10. A bot attempts a direct table update, journal mutation, force-release or another bot's identity: permission denied.
11. Sender restarts with pending attempts: recover durable state without submitting again.
12. Offline test job cannot access network trading hosts, SDK signing methods, real wallet secrets or live GitHub Actions dispatch.

## Integration / review boundaries

- First prototype commit should include only module interfaces, an in-memory deterministic fake and tests. Introduce CI-only DB integration in a later reviewed commit; no production migration.
- Explicitly verify the test runner cannot import `hyperliquid.exchange` or construct a trading signer. Keep the fake interface distinct from SDK order method names to avoid accidental live adapter substitution.
- All three original bot entry/exit/TP/SL decision rules remain untouched. Production integration is a **separate** proposal, with operator approval and a plan for protective exits during HOLD.
- No claim that offline tests prove actual Hyperliquid fill provenance or exactly-once real exchange submission.
- The earlier CI-only CLOID SQL edit was blocked; do not bypass that protection. A new CI-only prototype schema requires independent safety review before implementation.

## Acceptance criteria

Prototype accepted for *further offline review* only if it demonstrates one serialized fake dispatch per claim, durable ambiguous state through restart, strict bot/account isolation, no direct exchange calls, and no live authorization paths. All tests must run without credentials, network access or production database connections. Passing these gates does **not** permit deployment.

**Release state: NO-GO.** PR #40 remains draft and original three executors remain unchanged.
