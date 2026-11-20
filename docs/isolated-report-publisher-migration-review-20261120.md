# Isolated report publishing migration — review-only design (20 Nov 2026)

**NOT DEPLOYED.** No existing workflow, schedule, secret, Gist, repository permission,
trading executor, or Hetzner host is changed by this note.

## Actual current dependencies verified against `main`

- Daily, Intraday, and Aggressive execution workflows use `contents: write`,
  generate reports in their **trading runner workspaces**, `git reset --hard
  origin/main`, then push `reports/latest.json` and the date-stamped report
  straight to `main`, with `continue-on-error: true`.
- Intraday and Aggressive subsequently run timed protection loops in **the same
  workspace**. An intervening `main` change could alter the code the protection
  loops execute. A failed publish may be hidden behind an overall successful run.
- `daily_bot_report.py` reads all three bot states from private Gists with
  `GIST_TOKEN`, and **also fetches market data** for observational short
  research; it is not entirely offline. It reads **`reports/latest.json`**
  to preserve paper-short shadow history. Losing that prior snapshot silently
  changes the report's historical continuity.
- As read on 20 Nov, the repository's `reports/latest.json` was generated on
  **7 Nov 2026**. This proves that file is stale, not that any trading bot has
  or has not been running since.

## Read-only GitHub operation and visibility check (20 Nov 2026)

- The repository metadata returns `private: false` / `visibility: public`.
  The existing `reports/latest.json` and dated reports are therefore not
  an acceptable destination for new unredacted private trading records.
  **Do not post copies of sensitive report bodies or Gist contents in CI logs,
  PR comments, public artifacts or a new branch.** Review existing public
  report exposure and decide whether removal or access changes are needed,
  under separate explicit operator approval.
- GitHub Actions read-only list `GET /actions/runs?branch=main&per_page=100`
  showed its most recent `main` workflow run as **Execute Intraday,
  7 Nov 2026 00:07 UTC, cancelled**. The preceding Intraday runs on 6 Nov
  were successful. The repository's last report has a matching 7 Nov
  generation timestamp. The reviewed original bot workflow definitions
  are `workflow_dispatch`-only, with no GitHub `schedule` trigger.
  **Do not conclude bots have stopped trading**: an external dispatcher or
  server may exist outside this GitHub run history; current Gist and exchange
  account evidence was neither accessible nor requested.
- A safe operator check, before any new scheduler or bot dispatch, is:
  identify the authoritative prior dispatcher, confirm its health and
  intended trigger ownership without making changes, verify the absence
  of unexpected overlapping jobs, and separately verify any open
  Hyperliquid positions/protective exit coverage through an authorised
  read-only route. Do not restart a live bot or run a manual workflow merely
  to produce a fresh report.
- Source-only offline contract + Code Safety + disposable PostgreSQL
  checks all passed at commit `9403e1e4fb8b3c82920d8dd68cc09139104281ef`.
  This confirms **offline regression behavior**, not actual report delivery.

## Proposed migration sequence (not authorised to run)

1. Preserve the running bots and their protection loops untouched. Design a
   separate reporting **job/workflow** with a pinned reviewed checkout, no
   `HL_PRIVATE_KEY` or exchange-order identity, no checkout reset affecting a
   trading runner and a separate concurrency lock for published reports.
2. Decide on **private, durable** storage for sensitive report bodies and
   `latest.json` shadow-state history. The code repository is public; do not
   blindly upload the full detailed report to publicly accessible Actions
   artifacts, job logs or a publicly readable code branch. Decide retention,
   access ACL, backup, audit, and safe redaction before deploying.
3. Give the eventual reporter only the minimum **read** access required for
   three reporting Gists and approved market-data requests. Do not reuse or
   expand trading credentials. A generated report is not an authenticated
   exchange ledger and cannot authorise trading decisions.
4. Verify report output **before** publication using the strict, pure
   `report_snapshot_health_offline.py` gate: schema version, reporting-only
   flag, all three bot summaries, zero reported errors/accounting gaps,
   timezone-aware UTC timestamp and bounded age. Never interpret
   `METADATA_PASS` as proof of bots running, account reconciliation or
   permission to trade.
5. Independently verify no data leak and continuity: carry forward prior
   shadow state or fail closed if retrieval fails; test three simultaneous
   reporter starts, permission-denied storage, partial upload, stale source,
   report generation crash, retries, and restoration of last known good.
   Alert when report freshness or publisher job health fails.
6. **Only after separate operator approval**, move reporting out of the three
   executor workflows in a coordinated reviewed change, verify the alerting
   and rollback, then consider protecting `main` from direct bot writes.
   Never introduce a broad GitHub Actions bypass that enables arbitrary
   code writes. Keep open-position protection independent and effective.

## Current status

Synthetic report snapshot checks and current-workflow hazard detection
are **offline CI-only**. There is no private storage writer, separate
scheduled reporting service, verified continuity, approved migration or
deployment. **NO-GO** for live workflow modifications and trading.
