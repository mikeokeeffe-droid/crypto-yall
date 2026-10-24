# Trading state migration — staging only

**Live trading remains on Gists. Do not remove Gist credentials or enable database writes yet.**

1. Create a Supabase project and run `db/schema.sql` in its SQL editor.
2. Keep the Supabase service-role secret in server-side GitHub Actions secrets only; never in commits, logs, screenshots, or the client app.
3. Export the full state for Aggressive, Intraday, and Daily from their respective Gists, preserving complete JSON and timestamps. Take independent backups.
4. Validate each snapshot is a JSON object; inspect ownership, pending entry claims, peak return/profit, re-entry locks, and open-position reconciliation.
5. Import snapshots to staging; verify exact round-trip JSON equivalence and backup revisions.
6. Test optimistic concurrency, retries, database outage behavior, and recovery. Failed writes must halt new entries; never silently drop protection-critical state.
7. Compare Hyperliquid open positions and protective orders with saved ownership; resolve discrepancies before cutover.
8. Schedule a controlled cutover with no overlapping writers, followed by successful production monitoring and rollback verification.

**No automatic cutover is included in this branch.** The database schema is a foundation, not a complete migration or guarantee of uninterrupted monitoring.
