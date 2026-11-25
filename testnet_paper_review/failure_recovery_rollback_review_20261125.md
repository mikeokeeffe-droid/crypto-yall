# Failure recovery and rollback — Testnet-only design review

**Status: HOLD. Draft-only offline review, not an executable rollback or trading approval.**

## Verified offline demonstration
- A disposable SQLite journal retains one synthetic account claim across simulated process restarts. Transactional uniqueness stops simultaneous claims by competing fixture processes.
- Unknown, rejected and purported filled acknowledgments remain HOLD until synthetic reconciliation; no retry or reset is exposed.
- An emergency freeze is one-way, stored in the disposable journal, and remains active after a process restart. The existing claim is preserved for inspection.
- This demonstration has no order submitter, network client, signer, wallet, actual exchange acknowledgment, production database or server deployment.

## Failure-to-action matrix

| Event | Required behavior in a future reviewed live Testnet sender |
| --- | --- |
| Missing credentials, invalid identity, Mainnet URL or unexpected configuration | Fail closed *before* signing. Never fallback to the original bot or Mainnet. |
| Concurrent bot, duplicate request or stale snapshot | Reject and preserve durable claim; prevent another writer using a real shared locking service. |
| Crash before order submission, or crash after submission before acknowledgment | Persist the request before any network send; on restart assume unknown and require exact independent read-only reconciliation. Never blindly resubmit. |
| Exchange timeout, malformed reply or rejected acknowledgment | HOLD claim and prohibit retries until exact result verified. |
| Partial fill, unknown position, wrong side, unexpected notional or stop failure | HOLD and notify operator; independently verify actual fills and remaining exposure. Do not infer that cancel means closed. |
| SQLite corruption, storage outage, ambiguous state or missing journal | HOLD. Do not recreate a fresh empty journal and allow another request. |
| Emergency halt | Disable further order submissions, preserve claim and event history, and alert operator. Determine whether residual exposure remains by separate read-only account verification. |
| Rollback requested | Disable only the isolated Testnet sender first; snapshot and preserve state and order IDs; reconcile open positions and orders; obtain explicit separate approval for any cancel or reduce-only close. Never delete unresolved state. |
| Return to service | New independent security review and explicit user approval, with proven Testnet-only role and working live reconciliation, not just green offline tests. |

## Limitations and remaining blockers

1. The current disposable journal allows only a single fixture claim ever; it is **not** a production durable ledger, nor does it coordinate real remote workers, expiry, ownership, audit, service failures or operator identities.
2. The offline freeze is **not** an API kill switch, real process shutdown, or a way to close exchange risk.
3. Independent confirmation of Testnet collateral, actual agent scope/expiry, host isolation, deployed network restrictions, order reconciliation, and actual stop/exit controls is outstanding.
4. Existing Daily, Intraday and Aggressive executors are Mainnet-selectable and **must not** be activated or adapted for an initial Testnet order without additional isolation work.
5. All recovery tests are simulated. An end-to-end test of a genuinely isolated sender has **not** been performed.

**Decision:** NO-GO. Keep PR #46 draft, the original bots unchanged, the separate collector inactive, and all execution unapproved.
