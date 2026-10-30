# Staging isolation and promotion gate (PR #38)

**Status: NOT DEPLOYED.** This is a manual provisioning/runbook checklist, not proof of configuration. PR #38 remains a draft. No merge or production rollout is authorized by this document.

## Existing automated test boundary

The PR includes `.github/workflows/test-atomic-entry-reservations.yml`, which starts a disposable PostgreSQL 16 service under GitHub Actions and exercises reservation RPCs, identity permissions, concurrency, gateway, and failure/recovery tests. This ephemeral CI service **is not a provisioned Supabase staging project** and does not prove production safety on its own.

## Independent staging setup

1. Provision a new staging-only Supabase project and database, not a schema within production. Record its non-secret project identifier and region.
2. Ensure all connection strings, JWT signing/verifying configuration and service credentials are staging-only. **Never copy or expose production API keys, trading-wallet keys, webhook tokens, Gist IDs, or DB passwords.**
3. Create a dedicated GitHub Environment `staging` with environment approvals and limited secrets. Do not allow fallback to production secrets or to default-branch production workflows.
4. Create unique, restricted bot database identities for Daily, Intraday and Aggressive plus independent reconciler identities. Avoid service-role credentials in trading executors. Revoke unnecessary public/schema/table/RPC privileges.
5. Review SQL migrations for `SECURITY DEFINER` search paths, ownership, explicit grants and effective privileges **before** applying them to staging. Run `db/entry_reservation_identity_preflight_staging.sql` with an authorized read-only preflight account only after required staging roles exist.
6. Keep all staging schedules disabled and order placement blocked. Test only with fake exchange objects until a later explicitly approved, isolated testnet trial. Do not enable live Hyperliquid trading.
7. Run isolated CI and capture the SHA, checks, failures, logs and reviewed remediation. Then run SQL smoke tests on the newly provisioned staging database.
8. Re-run three-bot simultaneous reservation collisions, database outages, duplicate submission, TTL expiry, stale fencing, partial/ambiguous fills, restarts and durable reconciliation. Verify that **unknown** trade outcomes block reopening until independently reconciled.
9. Confirm ingress authentication, HTTPS verification, role isolation and emergency disable/rollback in staging. Perform a privilege audit and independent code review.

## Evidence required before any promotion proposal

| Gate | Evidence | Result |
| --- | --- | --- |
| Independent staging DB and secrets | Staging project identifier, credential separation review (no secrets pasted) | UNVERIFIED |
| CI success on current SHA | GitHub run URL and relevant job conclusions | UNVERIFIED |
| Staging SQL migration + smoke tests | Sanitized logs and reviewer | UNVERIFIED |
| Bot identity/RPC permissions | Denial tests for anonymous, service-role and cross-bot access | UNVERIFIED |
| Concurrency and fencing | Three-bot collision, expiry and duplicate-order tests | UNVERIFIED |
| Order reconciliation | Ambiguous/partial fill and restart recovery test results | UNVERIFIED |
| Rollback/emergency stop | Documented rehearsal and independent reviewer | UNVERIFIED |

**Promotion decision: NO-GO** until all gates pass and a separate, explicit production deployment decision is made. Do not auto-merge this draft PR.
