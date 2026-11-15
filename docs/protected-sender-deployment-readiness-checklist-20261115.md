# Protected sender deployment readiness — independent review handoff

**15 November 2026. PR #42 is DRAFT. TESTNET AND LIVE NO-GO.**

`sender_review/ci_only_deployment_readiness_manifest.json` contains 14
unverified gates, each with an owner and required evidence. The
offline validator and negative tests fail closed on any missing,
changed, duplicated or forged approvals, and **never** produce a GO result.

## What passing CI actually proves

The source-only interface checks and disposable PostgreSQL tests exercise
fixtures and restricted dummy roles. They do not establish GitHub-issued
runtime credentials, validated HTTPS/JWKS transport, effective host
sandboxing, live exchange provenance, order reconciliation, signing
isolation, safe exits, or operator authorization.

## Gates to clear outside this PR

1. Real GitHub workload identity and authenticated transport
2. Durable exact-request, bot and account binding and replay protection
3. Least-privilege production database roles and safe privileged functions
4. Effective host isolation and independently measured egress policies
5. Read-only exchange transport, host/proxy/TLS and API schema verification
6. Historical archive completeness beyond Hyperliquid retention limits
7. Account-wide ownership, manual trades and partial-fill reconciliation
8. Exclusive sender and coordinated removal of all five legacy execution paths
9. Exchange-enforced explicit-size reduce-only exits and protective risk controls
10. Unknown-ACK and crash-restart recovery with no blind retries
11. Alerting, kill switch, operational escalation, open-position rescue and rollback
12. Independent technical/security review of exact code and runtime artifact
13. Separate bounded testnet operator approval
14. Separate, later production operator approval

**The check marks in GitHub are not those approvals.** No synthetic fixture
can create trusted host attestation, attest independent security review,
or demonstrate testnet exchange behavior. Never copy the draft manifest
into a deployment configuration or treat its status fields as authorization.

No service or production bot is changed by this handoff. A future decision
must come from separately verified evidence and explicit human approvals
on the exact released commit; the review-only validator stays NO-GO.
