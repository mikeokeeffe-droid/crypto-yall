# PR #40 — protected journal boundary (design only)

**Status: DRAFT / NO-GO.** No changes to original bots, production databases, credentials, or exchange connections.

## Confirmed gap

The offline verified-claim wrapper rejects mismatched test identities, but `OfflineRestartJournal.reserve(bot=...)` still accepts any caller-supplied bot name. `mark_dispatch_unknown` also checks a token/fence without authenticating a caller. The direct-journal bypass audit intentionally demonstrates these behaviors. Passing those tests does **not** mean the bypass is resolved.

## Required production architecture (not implemented)

- Run **one** coordinated sender/claim service as the sole holder of database write permissions and exchange order-signing authority. Original bot workloads must have neither direct claim-table write permissions nor direct exchange trading credentials.
- Accept requests only via an authenticated workload channel. Derive the bot identity from independently verified service identity (for example, a scoped workload token with server-side verification), not a `bot` field, token, CLOID, or caller-selected header.
- Map each verified identity to a fixed bot, allowed environment, Hyperliquid account and operation. Fail closed if identity verification, revocation lookup, or policy data is unavailable.
- Expose narrow commands (request-entry, inspect-own-claim, reconcile, request-close); never expose a general-purpose journal method or arbitrary SQL to bot workloads.
- Use server-side transactionally bound immutable claim identity, scope, intent, fencing and idempotency key. Only the service may mark a dispatch attempt; persist uncertainty **before** any external side effect.
- Independently reconcile exchange orders, fills and current position before any bounded close. Do not infer close authority from the presence of a token/CLOID or from matching coin/direction.
- Protect the service from bypass: network isolation, least-privilege DB roles, secret separation, audit logs and explicit emergency stop. A second sender or direct executor API access is a **NO-GO**.
- Treat a journal restart, unavailable storage, stale verifier, or incomplete exchange history as **hold for review**, never automatic claim release or resubmission.

## Acceptance gates

1. Demonstrate that all three bot workloads cannot connect with journal write permissions, even if they know table names and claim identifiers.
2. Test Daily impersonating Intraday, token/CLOID/fence replay, account/environment mismatch, revoked/expired identity, and unavailable identity provider.
3. Test simultaneous requests, process crashes, ambiguous exchange acknowledgments, missing journal, stale reconciliation, and failed closes.
4. Independently verify real exchange order/fill provenance and position ownership for close requests, including mixed-bot and manually opened positions.
5. Keep live deployment blocked until design review, threat-model sign-off, integration tests and explicit approval.

## What current tests prove

They exercise **offline-only synthetic fixtures**. They prove that the existing wrapper can reject some spoofed requests and that the direct journal can be bypassed. They do not provide an authenticated production service, isolate real database credentials, or authorize any live order.
