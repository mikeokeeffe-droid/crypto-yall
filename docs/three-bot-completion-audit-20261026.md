# Three-bot completion audit — 2026-10-26

This audit reads the **main** branch execution workflows. It is not a production approval.

| Area | Evidence on main | Remaining proof |
| --- | --- | --- |
| Aggressive | Manual `execute-aggressive.yml`; profit-protection executor and 25-minute protection monitor | Verify entry/exit execution, loss caps, errors, and position recovery with simulated fills |
| Intraday | Manual `execute-intraday.yml`; protected executor and 55-minute protection monitor | Verify rapid exits, missed runs, restart recovery, and simulated partial fills |
| Daily | Manual `execute-trades.yml`; `hyperliquid_executor.py` | Verify Daily exit and profit-protection behaviour, sizing and loss controls |
| Shared positions | Each workflow uses a **different** GitHub Actions concurrency group | Cross-bot coordination is **not** guaranteed by workflow concurrency; test shared reservation fences end-to-end |
| Deployment | Staging PR #38 is draft; new DB roles are not deployed | Do not merge or enable live orders without review and cutover approval |

## Prioritized completion plan

1. Run offline, deterministic three-bot entry/exit scenarios against the **main** executors, with fake exchange and state adapters. Confirm every order path is guarded by a kill switch and risk cap.
2. Verify shared-account conflicting entries, restart recovery, partial fills, stale state, network errors and order retries. The separate GitHub concurrency groups are not a substitute for an atomic shared entry lock.
3. Reconcile and integrate only the proven safety changes from draft PR #38; do not activate its staging SQL or credentials as-is.
4. Perform independent review, limited paper/testnet acceptance and explicit approval before any live execution.

## Scope and immediate risk

These workflows contain `workflow_dispatch` only, not an automatic cron schedule. A manual/API dispatch can still invoke an executor that has access to private keys. The GitHub variables controlling kill switches must be checked independently before any manual run. This audit does not establish their current values.

All three bots must remain OFF while this work proceeds.
