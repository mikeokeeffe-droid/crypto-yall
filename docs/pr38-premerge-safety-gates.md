# PR #38 — pre-merge safety gates

This branch is staging-only. Do not merge it into the production executor branch until all gates below are reviewed and satisfied.

## Blocking finding: live Intraday entry path modified

`intraday_executor.py` adds a hard-coded `if True` return after the close/exit branch and before new order submission. Although fail-closed, merging this changes production entry behaviour even with every staging flag OFF.

**Required before merge:** Move the hard-coded entry block and the staging observer out of the production executor diff, or obtain explicit approval for a separately reviewed intentional entry shutdown. Retain and verify existing close-only protection semantics.

## Other merge gates

- Separate staging SQL, offline tests and read-only probes from changes to production workflows/executors where possible.
- Prove all three production order paths acquire and persist a durable reservation and intent **before** submission before advertising cross-bot protection as live. Current shared gate is an offline inspection adapter.
- Keep unresolved/timeout/ambiguous exchange orders fenced; require independently verified fills, positions and open orders before ownership release.
- Verify dedicated reconciler identity, minimal grants, transaction serialization, and replay/restart behaviour in disposable PostgreSQL.
- Re-run the complete isolated test suite and production-workflow regression tests on the exact merge candidate.
- Never deploy staging DDL to production, enable a trading workflow, change a kill switch, or switch Supabase persistence as part of this PR review.

Status: **NOT APPROVED FOR MERGE / NOT PRODUCTION READY**.
