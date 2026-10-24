# Atomic state update staging checklist

**Do not enable live Supabase writers yet.**

1. Verify independent backups of Aggressive, Intraday and Daily Gist JSON and their checksums.
2. Apply `db/atomic_state_update.sql` in the Supabase SQL editor after review.
3. Create a **synthetic** test row in a separate test project or test schema, never overwrite real trading state.
4. Confirm revision 1 updates to 2 and creates an exact revision-1 backup.
5. Confirm a second writer using revision 1 is rejected without changing state or backup.
6. Confirm invalid state and missing rows fail without partial writes.
7. Test database outage and ambiguous timeout behavior before any live bot migration.
8. Reconcile live Hyperliquid positions, protective orders, locks and pending claims; only then plan a staged cutover.

This SQL is a proposed database safeguard. Committing it does not apply it to Supabase.
