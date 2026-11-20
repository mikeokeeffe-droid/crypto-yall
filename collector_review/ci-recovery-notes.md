# Read-only collector: CI recovery and safety boundaries

The initial PR #41 workflow runs created on 11 November 2026 remained queued with zero jobs. GitHub Support reported that their check suite became out of sync and recommended **creating a new workflow run rather than re-running a stuck attempt**. Attempts to re-run the original workflows ended with a GitHub-side startup failure, before any tests executed.

This documentation-only change is intended to trigger fresh `pull_request` CI checks for PR #41. It does not change code, unlock network access, grant signing permissions, or deploy anything.

## Acceptance criteria

- **Read-only Testnet Collector Review (offline):** completes successfully on the new PR #41 head commit; includes the offline response, audit, identity, Linux host-probe, and systemd unit checks.
- **Code Safety Check:** completes successfully on that same head commit.
- Treat queued, startup-failed, cancelled, or skipped checks as **not validated**. Inspect the new run IDs and job logs rather than relying on the older run results.
- A green CI run still does **not** establish production server isolation, real Hyperliquid response provenance, account ownership, or authority to trade. The collector network transport remains disabled pending explicit separate review and approval.

Both PRs remain drafts pending further security review. Live trading remains NO-GO.
