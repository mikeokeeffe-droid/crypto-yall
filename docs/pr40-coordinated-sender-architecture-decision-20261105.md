# PR #40 — coordinated sender architecture and go/no-go boundaries

**5 November 2026. Architecture proposal only; NO-GO.** No trading code, SDK integration, production DB, workflows, wallet credentials or live account is modified.

## Recommendation

Keep Daily, Intraday and Aggressive **signal generation and risk decisions unchanged**. In a separately approved future project, route their *order dispatch* through **one account-scoped serialized sender**, instead of allowing each GitHub Actions worker to submit directly to Hyperliquid. A PostgreSQL claim is necessary for admission but is not itself a distributed exchange dispatch fence.

## Proposed responsibility split

| Component | Allowed | Forbidden |
| --- | --- | --- |
| Original signal bots | Calculate existing signals and desired side/quantity; request admission | Independently dispatch exchange orders after a local check; override shared claims |
| Authenticated admission coordinator | Atomically reserve account/DEX/coin and immutable pre-submit intent, CLOID and fence | Grant a second active claim while prior submission may be in flight |
| Single dispatch worker | Consume approved, committed intents, durably mark dispatch-unknown, serialize all orders per account/DEX/coin, call pinned SDK with saved CLOID | Reconstruct CLOID from untrusted input, replay ambiguous submissions, skip claim verification |
| Independent read-only evidence collector | Capture exchange orderStatus, fills, open orders, position snapshots and audit metadata | Hold trading credentials, submit/cancel orders, release claims |
| Separately privileged reconciler | Review provenance, netting and fill coverage; propose audited resolution | Infer ownership from same-side position or synthetic status; release on timeout alone |
| Operator | Approve migration, legacy-position handling, emergency procedure and production cutover | Assume test passing equals deployment readiness |

## Hard distributed-systems limit

A database transaction and a Hyperliquid order are **not one atomic operation**. Marking an attempt before the send protects against automatic double sends after a crash but can leave a reserved claim even if no order was transmitted. This is intentional fail-closed behavior. A shared lock held only during the HTTP request is insufficient after timeout: the request might still be accepted later.

For safety, the sender must never automatically transfer a possibly in-flight scope to another worker. There is no proven automatic, always-live, exactly-once guarantee here. To restore liveness after ambiguous sends, require independent evidence and an explicitly approved release policy, potentially manual intervention.

## Two migration designs for future review

**Option A — central serialized sender (preferred for consistency):** All three bots retain strategy computation; only a separate, audited service has trading-signing capability. The service validates immutable intent, serialized account scope and CLOID. All account-scope submissions must pass through it. Benefits: one dispatch choke point and simpler auditing. Costs: availability dependency, latency, secure signer hosting, failover/operational complexity, and possible HOLD during outage.

**Option B — per-bot direct sender with DB fence:** Each GitHub Actions worker checks an account-scoped DB claim and sends directly. This has a time-of-check/time-of-use race and bypass risk; **not accepted** without a stronger proof that reassignment and stale dispatch cannot overlap. A TTL/heartbeat alone does not supply that proof.

Even Option A cannot prevent manual trades or other API agents using the same account outside the service. Such activity must be detected and treated as ownership ambiguity. API-agent signer addresses must not be mistaken for the effective trading account.

## Proposed preflight and rollout gates

1. Inventory *all* production order/cancel/close callsites, workflows, API agents and manual account users. No bypass path may remain for the coordinated scope.
2. Design and review a trusted per-bot identity, approved account/DEX allowlist, immutable CLOID creation and intent journal, audit trail, DB privilege separation, durable uncertain-state policy and emergency halt.
3. Implement in a disposable environment, test competing workers and crash injection. Validate no duplicate order on retry, even if the first HTTP reply is lost; verify blocked claims persist through coordinator restart.
4. Test on a dedicated Hyperliquid testnet account only with explicit approval and bounded exposure. Demonstrate OID/CLOID/fill correlation and reconcile partial fills and account netting.
5. Decide how existing open positions without authenticated lineage are quarantined or migrated, and how TP/SL and kill switch work during sender outage or unresolved claim. No strategy or protective exit behavior is silently changed.
6. Coordinate an **all-three-bot** cutover; a partial rollout leaves uncoordinated senders. Provide a tested rollback that stops new submissions before reverting; reverting to concurrent direct senders while claims are unresolved is unsafe.
7. Require a new, explicit production authorization for all affected executor files, signing service, secrets, DB migrations, workflows and deployment.

## Current state

- Draft PR #40 has offline tests for claim uniqueness, pre-submit intent, order/fill structural comparison, history limits, restart recovery and a **non-authorizing** dispatch lifecycle model.
- **No** production sender, independent authenticated read-only collector, exchange-backed ownership ledger, CLOID DB migration, migration/rollback plan or production close gate exists.
- Passing CI confirms tests for synthetic/disposable behavior, not a proof of safe live integration.

**Decision: central sender is the preferred architecture for later review; deployment is NO-GO.** Preserve original Daily, Intraday and Aggressive executors and strategies unchanged.
