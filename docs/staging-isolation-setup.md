# Isolated staging environment — PR #38

Status: SETUP REQUIRED. This document is a runbook, **not evidence that staging exists**.

## Safety boundary

- Do not deploy PR #38 to production or merge it until the full review gates pass.
- Do not use production Supabase URL, service-role key, database credentials, exchange account, wallet/signing key, state Gist or webhook secrets in staging.
- Disable all live-trading schedules and order-capable execution in staging. Prefer mocked exchange responses; any later exchange integration tests must use an independently provisioned testnet account.
- Keep production GitHub Actions workflows and their secrets unchanged.

## Provisioning checklist

- [ ] Create a **new Supabase project** exclusively for staging, in a separate environment with independent database and credentials.
- [ ] Create dedicated, least-privilege **staging bot identities** (Daily, Intraday, Aggressive). Confirm one bot cannot impersonate another; never share a database service-role credential with execution clients.
- [ ] Create a distinct staging GitHub Environment named `staging`, with environment-protected secrets and approval rules. No fallback to production secrets.
- [ ] Establish a private staging HTTPS reconciliation endpoint with certificate verification and separate staging authentication. Deny unauthenticated writes.
- [ ] Configure a staging-only kill switch defaulting to OFF/blocked and require an explicit opt-in for any test execution.
- [ ] Seed synthetic fixtures only; never copy production account or customer data.
- [ ] Deploy the PR's reservation SQL/RPC solely to staging after reviewing privileges, RLS, grants, and revoke statements.
- [ ] Run the included SQL smoke test in staging and capture sanitized results.
- [ ] Test simultaneous entry requests from all bot identities; exactly one reservation must succeed for an overlapping risk slot.
- [ ] Test failed/slow database, expired TTL, retries, duplicate callbacks, stale fencing token, revoked identity, wrong bot identity, and ambiguous exchange fills.
- [ ] Confirm an unresolved order intent cannot be duplicated after TTL expiry and that recovery/reconciliation survives restarts.
- [ ] Configure alerting for auth failures, database downtime, unreconciled intents, repeated reservations, and kill-switch events; rehearse emergency stop and rollback.
- [ ] Obtain independent review of concurrency, privilege isolation, and failure modes. Record evidence before any live deployment decision.

## Acceptance evidence (fill only after verified)

- Staging Supabase project ID (non-secret):
- Staging endpoint domain (non-secret):
- Tested commit SHA:
- SQL smoke-test run and result:
- Concurrency/failure-mode test run and result:
- Privilege/RLS audit:
- Rollback rehearsal:
- Independent reviewer and approval date:

**GO/NO-GO:** NO-GO until all required checks above are verified. A passing CI workflow or smoke test alone is insufficient.
