# Backup validation checklist

This branch is preparation only. Do not enable a live state cutover.

- Confirm the existing Gist state audit succeeded.
- Export each bot's full JSON state into an access-controlled backup.
- Verify JSON object type, size and canonical SHA-256 digest after reading the backup.
- Record snapshot time and revision.
- Compare state with Hyperliquid open positions and active protective orders.
- Do not start database writers until rollback and concurrency checks pass.
- Keep the existing Gist credentials until the migration is fully verified.
