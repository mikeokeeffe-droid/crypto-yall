# PR #38 security acceptance status

**Decision: NO-GO for merge or live rollout.** This is an evidence ledger, not a release approval.

| Workstream | Implemented in draft | Outstanding before production |
| --- | --- | --- |
| 1. Authentication | Offline HS256 verification; distinct reconciler and executor scopes; bot-specific executor identities and signing keys for Aggressive, Intraday and Daily; offline valid/invalid and impersonation tests | Actual receiving gateway; dedicated issuer/key issuance, storage, rotation and revocation; identity-to-restricted-DB-principal binding; gateway integration test |
| 2. Database isolation | Disposable PostgreSQL trial revokes service_role direct DML and reservation RPC rights; role-switch tests | Production migration plan and credential separation; inventory/migrate all existing callers; prove deployed role privileges and rollback |
| 3. Three-bot integration | Mocked staging entry fencing, reconciler handoff/release, selected restart/failure tests | Full three-bot end-to-end runs with independent principals, exchange snapshots, pagination/partial fills, concurrency, restart, failure injection and audit evidence |
| 4. Review and rollout | Draft PR, CI workflows, review notes | Independent security review; approvals; canary and rollback plan; explicit live cutover authorization |

## Must remain unchanged

- Do not merge this draft into main or deploy staging grants to production.
- Do not switch on Aggressive, Intraday or Daily bots, modify secrets, production database, or kill switches.
- Never treat passing isolated PostgreSQL tests as proof that Supabase service_role is restricted in production.
- Staging grant SQL now revokes service_role direct DML and routine reservation RPCs; this is **not deployed** and does not provision a replacement executor identity. Actual production grants remain unverified.

## Acceptance gate

Only consider cutover after CI is green at the **final commit**, identity-to-DB-role end-to-end proof is captured, every production caller is migrated, independent review signs off, and the user explicitly approves deployment.

## Latest isolated acceptance additions

- Signed staging identity tests now explicitly reject Aggressive and Daily reconciliation requests before reading exchange evidence or invoking database RPCs.
- This is a **safety fence**, not three-bot integration. Aggressive and Daily must remain unsupported by the authenticated staging reconciler until separate end-to-end authorization and exchange-evidence tests exist.
- An independent reviewer must inspect the authentication gateway implementation, actual deployed grants, and migration sequence; no such review is represented as complete here.

## Staging grant hardening (commit 9293816)

The staging grant proposal now explicitly revokes direct table DML and routine reservation RPC access from service_role. This is intentionally fail-closed: no production or staging rollout is possible until a dedicated authenticated executor principal is configured. Existing PostgreSQL grants, inherited roles and function ownership still require inspection; revoking grants from service_role alone is not proof of effective isolation.

## Final integration review — 26 October 2026

The isolated PostgreSQL checks at commit `31082af` passed, including
three-bot concurrent reservation/claim and restart fence scenarios. Dedicated
ephemeral LOGIN checks also passed in disposable CI PostgreSQL. These are
meaningful staging proofs, **not** evidence of a deployed gateway or production
permissions.

**Critical remaining acceptance items (no cosmetic additions):**

1. **Real executor wiring:** Aggressive, Intraday and Daily production
   `execute_trade` entry paths do not currently invoke the staging shared
   entry fence. The offline tests extract their function ASTs and inject fake
   exchanges; they do not prove runtime protection. Review actual call sites,
   use a safe feature-gated integration plan, and test every order-opening path.
2. **Real gateway and identity:** Provision an authenticated receiving gateway,
   independent issuer/key management, revocation and dedicated DB principal
   mapping. The ephemeral CI PostgreSQL login is not a deployed service.
3. **Three-bot recovery evidence:** Capture full integration results with
   independent credentials and exchange snapshots, partial fills, pagination,
   concurrent entries, restart, uncertain orders, outages and audit trail.
4. **Production migration and review:** Inventory current callers and database
   grants, prepare rollback/canary, verify actual deployed permissions and
   obtain independent security approval plus explicit user authorization.

**Decision remains NO-GO.** Keep all bots OFF, do not merge, deploy, change
credentials, or submit orders. Stop adding isolated edge-case tests unless a
specific acceptance blocker requires them.
