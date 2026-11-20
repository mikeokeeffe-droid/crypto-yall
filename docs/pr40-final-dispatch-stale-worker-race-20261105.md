# PR #40 — final-dispatch stale-worker race review

**Draft-only safety review, 5 November 2026. NO-GO.** No production executor, workflow, trading wallet, exchange order, database migration, or runtime configuration is changed here.

## Finding

The disposable `ci_scoped_entry_claims` table provides an atomic uniqueness constraint per `(environment,effective_account,dex,coin)`; `ci_record_pre_submit_intent` commits a claim and immutable entry intent in one transaction. The synthetic restart reviewer checks the same intent and fence twice. **Neither mechanism alone proves a stale worker cannot submit a real order.** A worker can read a valid fence, pause, lose authority, and then call `exchange.market_open`. The original Daily/Intraday/Aggressive executors currently have no shared fenced dispatch adapter. The pinned Hyperliquid SDK supports a CLOID, but an exchange order does not atomically participate in a PostgreSQL transaction.

## Concrete time-of-check/time-of-use interleaving

| Sequence | Worker A | Coordinator / worker B |
| --- | --- | --- |
| 1 | A acquires scoped claim, fence 41, CLOID A, commits intent | |
| 2 | A checks fence 41 and sees it is current | |
| 3 | A pauses before the HTTP order send | Coordinator considers A expired and reassigns scope to fence 42 |
| 4 | | B obtains CLOID B and submits same-coin order |
| 5 | A resumes and submits with CLOID A despite a prior successful check | Both orders may reach Hyperliquid |

**Consequence:** A separate `check_fence()` followed by `market_open()` is not sufficient. A TTL, heartbeat, or another pre-send recheck only narrows the race window. Hyperliquid does not enforce our database fence; CLOID uniqueness correlates orders but cannot prevent two distinct CLOIDs from trading.

## Required policy before any live proposal

1. **No lease-based reassignment while dispatch might be in flight.** Once a durable intent is prepared or dispatch outcome is uncertain, keep the entire account/DEX/coin claim reserved through crashes, expiry and restart until a separately authorized reconciler establishes a safe terminal outcome. This is a safety-over-liveness choice: manual intervention may be needed.
2. **Single authorized dispatch coordinator.** An executor must not directly call the exchange after merely checking its own fence. Any future order sender must have one reviewed account-scoped serialization point with a durable dispatch journal. A local lock, per-bot Gist, or read-only fence query cannot serve this role across GitHub Actions runners.
3. **Dispatch uncertainty is irreversible without evidence.** Before sending, durably mark an attempt as potentially dispatched. On timeout/crash after that marker, never retry or release based solely on absent response, expired TTL or an empty orderStatus lookup. A lost response may still correspond to an accepted order.
4. **No reassignment while ambiguous.** Keep the original fence/claim blocked even when the worker is dead; do not create a new authorized same-coin intent until independently verified account-wide reconciliation and explicit release authorization. An exchange order can still be delayed after an HTTP timeout.
5. **Fail-closed controls.** All three bots must use the same approved sender and reservation domain before any rollout; direct SDK bypass paths, fallback unsized closes, stale executor versions, manual same-coin activity, and legacy positions require explicit policy. A sender process must never infer permission from synthetic `handoff_candidate` or `parsed_untrusted` results.
6. **Operational consequence.** A claim left unresolved may block otherwise profitable signals or protective exits. This tradeoff must be reviewed with the operator; no silent change to existing TP/SL or kill-switch semantics is approved.

## Acceptance tests for a separately reviewed implementation

- A checks valid fence then pauses; B attempts to replace A: **B cannot submit while A's dispatch remains potentially in flight**.
- A times out after sending, receives no OID: no automatic second CLOID, same-CLOID retry, or claim release.
- A crashes after marking dispatch-unknown but before sending: remain blocked until independently reconciled; absence of visible order is not automatic no-fill proof.
- A returns after B has a newer fence: A must be unable to reach a trading sender; if this is not guaranteed, **do not allow B to submit**.
- Two different GitHub Actions runners submit the same coin concurrently: one authorized dispatch domain, not just one successful local check.
- Same-side manual order, partial fill, account netting, history retention cap, API outage, stale read, and old unproven positions: HOLD.
- Crash between successful exchange send and audit DB write: retain the precommitted CLOID and uncertain state; independent reader and audit reconcile.
- All three original strategies retain their existing signal rules; no live testing or production deployment without separate explicit approval.

## Status and scope

This is a **design finding**, not proof of a working dispatch lock. Existing isolated PostgreSQL tests cover atomic claim creation, not the external send boundary. No CLOID migration or sender is implemented. The earlier proposed CI SQL CLOID edit was blocked by repository safety checks and must not be bypassed. Keep PR #40 draft, unmerged and NO-GO.

Related: `docs/pr40-order-lineage-reconciler-acceptance-contract-20261105.md`, `docs/pr40-original-executor-ownership-boundary-audit-20261105.md`.
