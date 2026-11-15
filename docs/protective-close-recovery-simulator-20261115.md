# Offline protective-close / unknown-ACK simulator — review only

**15 November 2026. No network, exchange signing, wallet or database access.**

The synthetic simulator in `sender_review/protective_recovery_simulator_offline.py`
consumes deliberately untrusted fixtures. All results have `state=HOLD`.
`fixture_matched=True` means only that the submitted *simulation inputs*
are internally consistent. It is **never** evidence of authenticated
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
