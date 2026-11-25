# Offline protective-close / unknown-ACK simulator — review only

**Originally 15 November 2026; P3 review clarified 22 November 2026.**
**No network, exchange signing, wallet or database access.**

The synthetic simulator in `sender_review/protective_recovery_simulator_offline.py`
consumes deliberately untrusted fixtures. All results have `state=HOLD`.
`fixture_matched=True` means only that the submitted *simulation inputs*
pass limited structural/fixture checks in this particular simulator.
That does **not** mean the inputs are complete, correct, or reconcilable.
It is **never** evidence of authenticated
exchange state, actual position ownership, reduce-only execution,
permission to submit, permission to retry or permission to release a fence.

## Modeled failure cases

- Position observation too old, wrong account/bot/coin/side, wrong position
  reference, stale fencing token, conflicting active nonce or claimed ownership
  not attributable to the requesting bot: **HOLD**
- Close request larger than the observed position, changed position size,
  missing/ambiguous order record, incorrect client order ID or account/coin
  mismatch: **HOLD**
- Unknown order acknowledgement: **HOLD, no blind retry**
- Partial fill (including remainder): **HOLD, no second close**
- Reported full fill: **HOLD**, because synthetic evidence alone cannot prove
  remaining exposure or safe lock release
- Cancelled/open/not-sent order: **HOLD**; cancellation does not imply a flat
  account and not-sent does not prove that retry is safe
- Duplicate nonce, stale fence, contradictory cumulative/remaining fill sizes,
  invalid/negative/NaN quantities or mismatching direction: **HOLD**

## P3 incident-triage labels (22 November review)

The separate `sender_review/recovery_triage_decision_table_offline.py`
turns simulated HOLD reasons into **manual-investigation categories and
unverified evidence requests**. It is not a recovery or execution policy;
its categories, `fixture_matched` and `simulated_remaining` must never be
interpreted as permission to retry, close, release a fence or resume a bot.
The category may also describe a hand-constructed `RecoveryReview` object;
no cryptographic proof or authentic exchange provenance is involved.

For `unknown_ack`, `not_sent` and `open`, the simulator intentionally
returns `simulated_remaining=None`, even when the fixture claims a numeric
remainder. It is **unknown**, not the full close size or a retry quantity.
For `partial`, `filled` and `canceled`, any `simulated_remaining` is a
**claimed, unverified synthetic value**, not a verified position, executable
close size or evidence that the account is flat.

## Explicitly out of scope in this offline simulator

- **Post-fill position reconciliation:** a genuine fresh position snapshot
  after a fill may differ from the pre-order size. The simulator currently
  requires `position_size == observed_position_size` and does **not**
  establish `position_before - verified_fills == position_after`.
  Its conservative HOLD therefore does not demonstrate correct recovery
  accounting for a post-fill snapshot.
- **Shared-account, shared-coin bot attribution:** the simulator accepts one
  asserted bot/position at a time. It cannot reconcile the net exchange
  position against per-bot inventory, overlapping orders or fills for Daily,
  Intraday and Aggressive, and cannot detect all unattributed remainders.
- **Real provenance and reservations:** `owned_by_requesting_bot`, observation
  age and `seen_nonces` are caller-supplied synthetic data. A missing
  `active_nonce` is not proof of an available reservation. A fixture's CLOID
  passes format checks only, and is not verified against the journal's
  derived CLOID or real exchange order lookup.
- **Actionable emergency exits:** no exchange-resident protection, flatten
  procedure, two-person recovery approval, durable HOLD-age alerts or safe
  fence-release mechanism is implemented. Remaining exposure may persist
  during HOLD. These are requirements for a separately reviewed future
  system, not reasons to relax this simulator's HOLD result.

## Standalone three-bot netting arithmetic (offline only)

The independent synthetic checker in
`sender_review/shared_account_reconciliation_offline.py` and its tests
`sender_review/test_shared_account_reconciliation_offline.py` describe
a **non-authorizing arithmetic exercise**, not a solution to shared-account
ownership. They require one synthetic allocation for each of Daily,
Intraday and Aggressive and compare signed before/after positions and
claimed per-bot fills against the claimed net account position.
Missing, duplicated or cross-account fills, inconsistent arithmetic and
offsetting long/short claims are categorized as **HOLD**.
Even perfectly matching figures remain HOLD and cannot authorize any
retry, protective close, lock release, sender or resumption.

**Not proven:** fill-history completeness; authenticated exchange
observations; freshness and sequencing; reliable historical position
attribution when bots share one netted exchange position; account-wide
nonce reservations; fill/CLOID linkage to the durable journal; or safe
account recovery. The inputs, IDs, account sizes and bot allocations
are caller-provided synthetic fixtures, not trusted exchange evidence.
A true live reconciliation path requires a separate authenticated
read-only adapter, complete timestamped and paginated fills, immutable
provenance, and a reviewed operator process. This standalone arithmetic
must never be connected to a signer or live trading state.

## Required before any testnet transport or trading

The real sender must independently authenticate GitHub workload identity,
verify a persistent account-wide nonce and fence, fetch authoritative
full-account order/fill/position history, attribute legacy and current
positions without guessing, compare order identifiers and signatures, and
enforce exchange-native bounded reduce-only closes. Recovery must include
a defined operator escalation path for unresolved ACKs and open positions,
with rehearsed protective exit and outage policy. The simulator cannot
validate real exchange semantics, network races, server restarts or operator
availability.

**Do not deploy this as a trading recovery engine. PR #42 remains draft.
Testnet and live execution remain NO-GO.**
