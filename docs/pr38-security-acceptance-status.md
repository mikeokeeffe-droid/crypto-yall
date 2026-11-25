# PR #38 security acceptance status

**Decision: NO-GO for merge or live rollout.** This is an evidence ledger, not a release approval.

| Workstream | Implemented in draft | Outstanding before production |
| --- | --- | --- |
| 1. Authentication | Offline HS256 verification; bot-specific executor identities and signing keys; a WSGI-callable staging handler selects per-bot restricted LOGINs; simulated HTTP and disposable PostgreSQL identity tests | Gateway deployment, dedicated issuer/key issuance, storage, rotation and revocation; TLS/network policy; production grants and runtime identity-to-DB-principal proof |
| 2. Database isolation | Staging RPCs validate protected bot-to-LOGIN mappings against PostgreSQL `session_user`; direct-RPC cross-bot attempts are denied for all three disposable LOGINs; trial revokes service_role direct DML and reservation RPC rights | Provision the three restricted identities and protected mappings in staging, review deployed grants/role memberships, inventory callers, and prove rollback |
| 3. Three-bot integration | Mocked staging entry fencing, reconciler handoff/release, selected restart/failure tests | Full three-bot end-to-end runs with independent principals, exchange snapshots, pagination/partial fills, concurrency, restart, failure injection and audit evidence |
| 4. Review and rollout | Draft PR, CI workflows, review notes | Independent security review; approvals; canary and rollback plan; explicit live cutover authorization |

## Must remain unchanged

- Do not merge this draft into main or deploy staging grants to production.
- Do not switch on Aggressive, Intraday or Daily bots, modify secrets, production database, or kill switches.
- Never treat passing isolated PostgreSQL tests as proof that Supabase service_role is restricted in production.
- Staging grant SQL revokes service_role direct DML and routine reservation RPCs. The protected LOGIN-to-bot mapping is implemented and tested only with disposable roles; no staging identities or grants have been provisioned. Actual production grants remain unverified.

## Acceptance gate

Only consider cutover after CI is green at the **final commit**, identity-to-DB-role end-to-end proof is captured, every production caller is migrated, independent review signs off, and the user explicitly approves deployment.

## Latest isolated acceptance additions

- A callable-only reconciliation receiver now binds all three bot-specific JWT identities to server-configured exchange clients and distinct restricted reconciler LOGINs. PostgreSQL `bot_reconciler_identities` additionally binds each LOGIN to one bot for owner transitions and intent reads. Reconciler LOGINs receive no direct SELECT or DML on protected intent, reservation, ownership, or identity tables; scoped SECURITY DEFINER RPCs provide the required reads.
- Offline receiver tests and disposable PostgreSQL tests cover request/authentication rejection, synthetic exchange evidence, effective grants, per-bot database identity isolation, and concurrent no-fill release. These remain test-environment evidence, not a staging deployment or live authorization.
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
2. **Gateway operations and identity:** The executor and reconciliation
   receivers are callable-only and create no listener. Provision and
   independently review hosting, TLS/network policy, issuer/key lifecycle,
   secret storage, audit/alerting, and dedicated staging DB principals before
   deployment. Ephemeral CI PostgreSQL LOGINs are not deployed service identities.
3. **Three-bot staging evidence:** Run the full receiver and recovery tests on
   the approved isolated staging database, then capture actual identity,
   effective-grant, exchange-evidence, and audit results. Disposable tests do
   not prove staging permissions or operational controls.
4. **Production migration and review:** Inventory current callers and database
   grants, prepare rollback/canary, verify actual deployed permissions and
   obtain independent security approval plus explicit user authorization.

**Decision remains NO-GO.** Keep all bots OFF, do not merge, deploy, change
credentials, or submit orders. Stop adding isolated edge-case tests unless a
specific acceptance blocker requires them.

The [staging deployment-readiness runbook](pr38-staging-deployment-runbook.md)
and [placeholder configuration checklist](templates/pr38-staging-gateway-config.example.yaml)
are preparation artifacts only. The draft now includes a callable-only host adapter with startup
LOGIN/grant/mapping checks, injected secret resolution, a TLS-verifying HTTPS
client restricted to explicitly allowlisted private destinations, bounded
requests/responses, and redacted audit events. The HTTPS transport has only
offline mocked-network tests. It has not been deployed or connected to a real
secret manager; no real identities or destination allowlist are configured and
deployment is not authorized.
