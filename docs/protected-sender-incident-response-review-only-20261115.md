# Protected sender incident response and three-bot cutover — review handoff

**15 November 2026 · PR #42 DRAFT · REVIEW-ONLY · TESTNET/LIVE NO-GO**

This is a proposed **human-operated response runbook**, not a deployed
incident system, an exchange automation, a sign-off, or a trading instruction.
It documents the release-blocking behavior that future runtime code, monitoring,
host permissions, and an independent reviewer must demonstrate. None of these
operator procedures has been exercised on a real exchange account. The
current original workflows remain signer-enabled and unchanged.

## Non-negotiable safety invariant

**Never confuse "no new order allowed" with "an existing open position is
protected."** On a sender/collector outage, new entries and pyramids must fail
closed, but existing exposures need an independently reviewed and available
protection/rescue path. Do not declare the cutover safe merely because the
journal returns HOLD.

At all times: no blind send/retry after an unknown outcome; no automatic fence
release based on missing records; no unsized close; no bot adoption of manual
or legacy positions; no rollback that restores a second writer.

## Proposed incident decision matrix (NOT implemented)

| Event / observation | Proposed automatic behavior to verify before release | Human escalation / independently needed evidence |
| --- | --- | --- |
| Remote identity/JWKS, TLS, source/run binding or clock invalid | Reject request before intent recording; no mutation | Security investigates issuer/transport and exact revision, restores only after independently observed checks |
| Collector unavailable, API rate-limited, history partial/truncated or stale | Block new entries and closes whose safe size/owner cannot be proven; keep pending attempts fenced | On-call reviews effective account/DEX, outstanding orders, all open positions, retention gaps and alternative verified source |
| Sender unavailable or signing service exits | Deny new entries/pyramids; prevent competing restart/retries; record outage | Immediate risk escalation if any position may be open or an exit may be due; confirm emergency-protection path exists before a cutover |
| Send timed out / lost ACK / process crashed after attempt started | Persist UNKNOWN/HOLD, keep account and coin fences; never auto-resend or assume flat | Obtain independently authenticated order status and complete fills using CLOID/OID, both order and account history, before any human-approved transition |
| Partial fill, canceled remainder, contradictory order data | No new claim/close based on presumed requested size; HOLD | Reconstruct actual filled and remaining exposure, open order status and reduce-only requirements |
| Position size/side/owner disputed; manual or pre-cutover trade exists | Do not adopt position or infer one bot owns aggregate exposure; block automatic close | Independent account-wide baseline, order/fill attribution and risk-owner decision; isolate or resolve unowned legacy exposure |
| Protective close rejected, delayed, wrong-size or unknown | Escalate CRITICAL if exposure exists; block duplicate unbounded closes; never claim a position is protected | On-call must assess current exchange position, open orders, liquidation risk, and the *approved* manual/exchange emergency procedure |
| Monitoring, alert delivery or human coverage unavailable | No new cutover or rollout; the service is NO-GO for unattended live operation | Operator validates two independent alert paths, acknowledgement, staffed response and failover plan |
| Kill switch or proposed rollback while outcome unknown | Stop **new** strategies; preserve unresolved attempt record and writer exclusivity; no key restoration to old bots | Review existing position protection first. Resume or rollback only on explicitly approved single-writer plan after independent reconciliation |

For all rows, "automatic behavior" is a **requirement for future implementation**,
not a statement that PR #42 or any running service enforces it.

## Five legacy execution invocations that must cut over together

1. Daily: `execute-trades.yml` → `hyperliquid_executor.py`
2. Intraday entry: `execute-intraday.yml` → `intraday_profit_protection.py`
3. Intraday protection-only recurring calls in that workflow
4. Aggressive entry: `execute-aggressive.yml` → `aggressive_profit_protection.py`
5. Aggressive protection-only recurring calls in that workflow

The three executors and two wrappers must preserve Daily/Intraday/Aggressive
strategy behavior, position limits, leverage, Aggressive pyramids, exit signals,
profit floor, trailing giveback and USD-loss protection. Before any cutover,
confirm **all five** no longer receive `HL_PRIVATE_KEY`, can no longer make
direct Hyperliquid order/leverage mutations, and cannot bypass the exclusive
sender over network egress. CI source scans alone cannot prove this on a host.

## Proposed human response sequence (requires operator review)

1. Identify the actual account/network/DEX and inspect recent durable attempt
   records. If any status is unknown, leave the nonce and fence held.
2. Suspend **new entries and pyramids** through the *approved* control plane.
   Do not simply kill all protective checks while positions may remain.
3. Independently query current exchange positions, open orders, order-by-CLOID,
   and complete fills with recorded provenance. Document missing or conflicting
   history; never treat absence of an OID as proof that an order was not sent.
4. If position or protection status is uncertain, escalate to a staffed human
   risk owner immediately. Any manual close/cancel action must follow a separately
   reviewed, exchange-specific procedure with real-position confirmation,
   bounded size, direction, and reduce-only handling. **This PR does not provide
   that procedure or authorize a manual trade.**
5. Keep the original signer access revoked during a completed future cutover;
   do **not** restart old workers while the new writer or unknown attempt could
   still be active. Reconciliation and explicit single-writer approval must
   precede any rollback/restart.
6. Record incident timeline, source evidence, alert acknowledgement,
   accountable operator, risk decision and independent review; do not edit
   journal history to turn HOLD into GO.

## Testnet drill and acceptance evidence required (not yet obtained)

- Independently establish zero-position and nonzero-position baselines, with
  complete ordered/fill history and manual/legacy trade treatment.
- Simulate sender loss before send, after durable `attempt_started`, and after
  exchange acceptance but before ACK. Show no automatic duplicate order.
- Exercise partial fills, rejected/canceled protective closes, changing position
  sizes, stale read sets, manual intervention, simultaneous bots and restart.
- Show at least one independently reviewed way to protect an **already-open**
  position during a sender outage. Demonstrate it does not enable a second
  unsupervised writer or unbounded close.
- Capture timed alert delivery and human acknowledgement, real effective host
  restrictions/roles, exact Git commit and deployed artifact digest.
- Obtain separate explicit operator authorization for *testnet read access*,
  then for any bounded testnet trade drill, followed by independent
  security/trading-risk review. Production requires distinct later approval.

## Current status and owner handoff

**NO-GO.** All runtime capabilities and drills above remain **UNVERIFIED**.
PR #42's successful disposable PostgreSQL and fake signed identity tests do
not constitute evidence that Hyperliquid orders or emergency exits are safe.

Suggested ownership: operations owns alerting and handoff; security owns
real issuer/HTTPS, signer isolation and least-privilege controls; risk owns
position/exit reconciliation and rescue policy; independent approval must
cover all three before any testnet action. See the 14-gate manifest at
`sender_review/ci_only_deployment_readiness_manifest.json`.
