# PR #40 — isolated coordinator process boundary (design and acceptance plan)

**Status: DRAFT / LIVE NO-GO.** This is an offline review artifact, not a deployed service. Original Daily, Intraday and Aggressive executors are unchanged.

## Threat model

The same-process `OfflineProtectedJournalFixture` cannot isolate `_journal` or its SQLite path from a caller running in the same Python process. The bypass tests deliberately show that a caller can access the private attribute or reopen the database. Python naming conventions, a wrapper, and an opaque claim token do **not** establish security isolation.

## Required isolation

1. **Separate processes and permissions.** Run the coordinator in a distinct service identity. Give only the coordinator access to the claim database and exchange trading credentials. Bot process identities must have no database write role, no journal file access, and no exchange order-signing keys.
2. **Authenticated request channel.** Authenticate each workload at the service boundary; derive bot identity from a verified principal mapped to allowed account/environment/operations. Reject any caller-supplied bot identity that differs. Do not trust a `bot` string or a claim token as proof of identity.
3. **Narrow service contract.** Only accept scoped entry-intent, claim-status, reconcile and close-review requests. No arbitrary SQL, raw journal methods, generic dispatch, or unbounded market close endpoints. Entry intents remain review-only until separate deployment approval.
4. **Durable claim authority.** Use a transactionally enforced unique claim per (environment, account, dex, coin) with immutable verified bot owner, monotonic fencing, idempotency, durable pre-dispatch uncertainty and restart-safe reconciliation.
5. **Independent exchange provenance.** Before close, verify the exact account, coin, side, current position size and independently attributable orders/fills. If provenance is incomplete, hold for manual review; never infer ownership from a same-side position.
6. **Operational controls.** Restrict ingress, rotate/revoke workload credentials, audit all decisions, prevent direct order pathways, and provide a tested kill switch. Fail closed on auth, database, service or exchange ambiguity.

## Offline acceptance tests to build next

- A simulated bot principal cannot read or write the journal via the service interface; attempted arbitrary methods are denied.
- Spoofed bot identity, unknown/revoked/expired principal, account/environment mismatch and token replay all hold.
- Two simultaneous bots competing for one scope cannot both reserve; distinct scopes remain independent.
- Service crash after durable marker, missing/corrupt journal and ambiguous fake exchange acknowledgment cannot trigger duplicate submission.
- Close requests from a different bot, unknown/manual positions, and mismatched side/size all hold.
- **Deployment gate:** verify actual process/database ACL isolation in a non-production environment. Unit tests alone cannot establish this.

## Explicit unresolved blocker

No dedicated coordinator process, authenticated transport, restricted DB role, credential separation, or exchange-side ownership reconciliation exists in PR #40. Until these are implemented and independently verified, **NO-GO for live integration**.
