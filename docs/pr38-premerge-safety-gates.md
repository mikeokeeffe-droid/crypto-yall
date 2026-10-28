# PR #38 — pre-merge safety gates

This branch is staging-only. Do not merge it into the production executor branch until all gates below are reviewed and satisfied.

## Blocking finding: production Supabase credential boundary is unverified

The staging branch includes `supabase_state_store.py`, and Intraday imports it only inside its state load/save methods. Persistence is disabled unless `SUPABASE_STATE_ENABLED=ON`; when enabled, the adapter uses `SUPABASE_SERVICE_ROLE_KEY` for the `bot_state` REST API. Do not set this flag or provide a production service-role key until an independent review verifies the deployed role, table/RPC grants, CAS behavior, and every caller. Offline PostgreSQL role tests do not establish the Supabase REST credential boundary.

**Required before production integration:** Keep production Supabase persistence disabled until the credential boundary and least-privilege access have been independently verified. Preserve existing entry and close behavior unless a separate change is explicitly reviewed.

## Other merge gates

- Separate staging SQL, offline tests and read-only probes from changes to production workflows/executors where possible.
- Prove all three production order paths acquire and persist a durable reservation and intent **before** submission before advertising cross-bot protection as live. Current shared gate is an offline inspection adapter.
- Keep unresolved/timeout/ambiguous exchange orders fenced; require independently verified fills, positions and open orders before ownership release.
- Verify dedicated reconciler identity, minimal grants, transaction serialization, and replay/restart behaviour in disposable PostgreSQL.
- Re-run the complete isolated test suite and production-workflow regression tests on the exact merge candidate.
- Never deploy staging DDL to production, enable a trading workflow, change a kill switch, or switch Supabase persistence as part of this PR review.

Status: **NOT APPROVED FOR MERGE / NOT PRODUCTION READY**.
