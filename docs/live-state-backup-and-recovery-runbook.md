# Live bot state backup and recovery runbook

**Do not migrate or change live state until each gate is signed off.**

## 1. Capture an immutable snapshot for each bot

The read-only three-bot audit has passed. An audit is **not a backup**.

For Aggressive (`aggressive_state.json`), Intraday (`intraday_state.json`) and Daily (`crypto_yall_state.json`):

- Arrange a maintenance window: pause scheduled writers and profit-protection workflows **only after confirming live exchange-side protective orders remain active**. Never pause exchange-side protection merely to take a backup.
- Export the full raw JSON from the bot's existing private Gist using an authorised, trusted machine. Do not copy state into a GitHub commit, issue, Actions log, chat, or public artifact.
- Store each export in a private encrypted backup location with restricted access. Record UTC time, Gist ID, filename, file size and canonical SHA-256 digest.
- Export a second independent copy to an encrypted rollback location. Keep the original Gist unchanged.
- Verify both exported copies offline with `python scripts/verify_state_backup.py SOURCE.json BACKUP.json`. This comparison requires the original JSON as a separate file; comparing two copies of the same export does not establish source fidelity.
- Re-read the Gist after the snapshot and compare canonical digest to detect writes during backup. If changed, re-snapshot before proceeding.

## 2. Reconcile live trading exposure

For each bot, inspect Hyperliquid positions and orders against its state. Confirm open positions, reduce-only stop orders, take-profit orders, peak-profit values, trailing locks, pending claims, and any pending notifications. Record unresolved mismatches; do not cut over with mismatches.

## 3. Validate database safely

- Review `db/atomic_state_update.sql` before applying. Its merge into GitHub **does not** deploy it.
- Use an isolated Supabase **test project** with the schema and synthetic data; never use actual live bot state for a first write test.
- Confirm service-role-only RPC access; reject unauthenticated/anon calls.
- Verify revision N -> N+1 and exact pre-update backup for each synthetic state.
- Confirm stale revision, invalid JSON, missing row, forced database failure and concurrent writers do not corrupt state.
- Test restoration from the saved pre-update backup in the isolated project, including the failure path.
- Treat network timeouts as ambiguous writes: re-read revision and reconcile rather than blindly retry.

## 4. Cutover gate

Require a verified and timestamped backup for **all three bots**, successful isolated database write/recovery tests, clean position/order reconciliation, a documented rollback, and explicit approval before changing any live executor. Migrate one bot at a time, observe multiple successful runs, and preserve the Gists during the observation period.

## 5. GitHub cleanup (after stability)

Archive old run logs as required, delete obsolete merged branches, review redundant workflows/scripts and unused secrets. Never delete Gist credentials, snapshots or rollback paths until the migration is demonstrably stable.
