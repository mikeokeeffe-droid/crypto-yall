# PR #40 — Read-only collector security gate and implementation handoff

**Review date: 2026-11-11 · DRAFT · LIVE NO-GO.** This is a security-gate decision for the *existing* Daily, Intraday and Aggressive bots. It grants no approval for a network connection, live trading, production DB migration, credential change, PR merge, or deployment.

## Findings from current branch

- Latest reviewed baseline `a30e208`: four CI workflows green. The tests use disposable PostgreSQL and synthetic exchange data.
- `offline_ci_info_capture_integrity.py` binds a synthetic SHA-256 digest, time, account, token, fence, CLOID and request type to supplied bytes. **A matching digest proves only integrity relative to a caller-supplied manifest; it cannot authenticate a Hyperliquid origin or establish complete history.**
- Existing `offline_hyperliquid_fill_window_audit.py`, `offline_hyperliquid_retention_gate.py`, `offline_hyperliquid_transport_plan.py`, and `offline_hyperliquid_capture_provenance.py` implement useful fail-closed **offline policy**, not a deployed network collector.
- The isolated `ci_sender_reviewer` has disposable read-only SQL access. It is **not** an authenticated live-exchange collector. An attempted additional SQL capture-role change was blocked; **do not retry or work around that change under this review**.
- Original bots retain direct exchange order methods; a real single-writer sender, authenticated reconciler, and vetted safe-close protocol do not yet exist. Passing CI does not address these P0 gaps.

## Confirmed external protocol constraints

Official Hyperliquid documentation describes `POST /info` reads, including `orderStatus` and `userFillsByTime`. The latter has **at most 2,000 fills per response**, only the **10,000 most recent fills** available, and **inclusive** `startTime` / `endTime` boundaries. Requests have weighted IP rate limits; `orderStatus` is weight 2, other read calls may be weighted higher and fill reads carry additional cost per returned item. Consult the current docs again before any implementation.

Sources:
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals

**Important:** Synthetic `next_cursor` fixtures in this PR are *not* an implemented Hyperliquid paging protocol. A public account query does **not** authenticate control of that account.

## Required security proof before proposing real read-only access

| Gate | Required evidence | Current decision |
| --- | --- | --- |
| C1. Operator-pinned scope | Approved master/sub-account, environment, perp DEX, exact official host, account-address verification independent of bot payload and agent signer | NOT VERIFIED |
| C2. Collector isolation | Standalone OS identity with no trading signer, exchange write path, live bot import, order authority, production DB mutation, or broad credentials; permissions verified as the effective process | NOT VERIFIED |
| C3. Controlled transport | HTTPS cert verification, exact host and `/info`, DNS/redirect/proxy/SSRF protections, fixed read-only request allowlist, bounded time/response size/rate budget, deterministic stop and logging | NOT IMPLEMENTED |
| C4. Genuine request provenance | Capture actual canonical request, pinned account, endpoint, OID/CLOID, time window, TLS/HTTP metadata, local clock and response hash *outside* server response; immutable audit access control | NOT IMPLEMENTED |
| C5. Account-wide coverage | Independently read order, unique fill IDs and all same-coin orders, including manual activity, open orders and live position; require durable pre-submit baseline | NOT VERIFIED |
| C6. Bounded history | Correct inclusive time windows and same-ms ties, no skipped or duplicated `tid`, fail closed on 2,000 response saturation, retention 10,000, gaps or rate limits; use independent archive for older evidence | NOT VERIFIED |
| C7. No automatic authority | Unknown, partial, failed, missing, stale or conflicting evidence => HOLD; collector cannot release claim, assign ownership, approve closes, or cause retries | OFFLINE POLICY ONLY |
| C8. Independently reviewed non-production check | Code and permission review, fixture/fault tests, explicit operator permission before a read-only testnet network request; audited rollback and incident response | NOT APPROVED |

## Minimal staged implementation

1. **Freeze additional overlapping fixture work in PR #40.** The branch is already very large. Consolidate the existing scope, parsing, window and retention guards into a single reviewed collector contract; remove contradictory assumptions before adding another new data model.
2. **Separate small reviewable collector change:** implement a dependency-injected, *network-disabled-by-default* read-only transport interface with strict configuration, a fixed request builder and a capture-envelope audit output. Unit tests must prove that invalid scopes, redirects, proxy overrides, wrong account, malformed payload, timeouts, 429 and capped windows produce HOLD. No database privilege changes.
3. **Security review before network:** verify isolated runtime identity and permissions, end-to-end provenance, effective egress restrictions, actual Hyperliquid schema mapping, rate weights and no signing or `/exchange` imports. Do not confuse SDK import bans with proven OS egress restrictions.
4. **Explicit approval needed for testnet-only reads.** Even read-only calls are not part of PR #40's current authorization. Select a designated testnet account after scope review and prove actual request-to-response binding; never use the current live bots or production account by default.
5. **Reconciliation remains HOLD** until complete independent evidence, a separately approved fenced handoff, and the single serialized sender + bounded reduce-only close paths exist. Treat legacy positions as unattributed until explicit operator investigation.

## Stop conditions

A single missing historical interval, uncertain API retention, same-ms fill tie, unexpected order, ambiguous response, missing pre-submit baseline, identity mismatch, unexpected network destination, loss of audit integrity, or a failed CI check is **NO-GO** for releasing a lock, retrying a trade, attributing position ownership, or closing a position automatically.

**Decision:** PR #40 stays **draft/unmerged**; original executors, live Actions workflows, Hyperliquid keys, production database and permissions remain unchanged. The next step should be a focused independent collector review—not further synthetic check-count inflation.
