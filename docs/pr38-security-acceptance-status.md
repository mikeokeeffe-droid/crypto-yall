# PR #38 security acceptance status

**Decision: NO-GO for merge or live rollout.** This is an evidence ledger, not a release approval.

| Workstream | Implemented in draft | Outstanding before production |
| --- | --- | --- |
| 1. Authentication | Offline HS256 signature verification and opt-in staging entry/release wrappers; mocked positive and negative tests | Actual receiving gateway; dedicated issuer/key management and rotation/revocation; identity-to-restricted-DB-principal binding; gateway integration test |
| 2. Database isolation | Disposable PostgreSQL trial revokes service_role direct DML and reservation RPC rights; role-switch tests | Production migration plan and credential separation; inventory/migrate all existing callers; prove deployed role privileges and rollback |
| 3. Three-bot integration | Mocked staging entry fencing, reconciler handoff/release, selected restart/failure tests | Full three-bot end-to-end runs with independent principals, exchange snapshots, pagination/partial fills, concurrency, restart, failure injection and audit evidence |
| 4. Review and rollout | Draft PR, CI workflows, review notes | Independent security review; approvals; canary and rollback plan; explicit live cutover authorization |

## Must remain unchanged

- Do not merge this draft into main or deploy staging grants to production.
- Do not switch on Aggressive, Intraday or Daily bots, modify secrets, production database, or kill switches.
- Never treat passing isolated PostgreSQL tests as proof that Supabase service_role is restricted in production.
- Existing staging grant SQL still includes direct DML for service_role; isolated restricted-grant trial does not remove that production blocker.

## Acceptance gate

Only consider cutover after CI is green at the **final commit**, identity-to-DB-role end-to-end proof is captured, every production caller is migrated, independent review signs off, and the user explicitly approves deployment.
