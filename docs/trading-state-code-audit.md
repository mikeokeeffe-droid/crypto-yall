# Trading bot code audit — pre-cutover

Scope: Aggressive, Intraday, Daily, state persistence, profit protection, GitHub Actions, and Supabase.

## Confirmed findings
- Daily state is handled in `hyperliquid_executor.py`, not a separate daily executor.
- Daily `save_trading_state` uses one Gist PATCH with no retry; an unsuccessful response raises.
- Aggressive and Intraday state writes still use Gist PATCH, with limited rate-limit retries. Exhausted quota remains an unresolved dependency.
- Intraday Telegram diagnostics can call `base.save_state(_state)` to clear a review flag, adding a state write during notification handling.
- Both execute workflows run repeated profit-protection checks and therefore depend on persistent state availability.

## Must pass before any live cutover
- Full JSON snapshots for all three bots, independently backed up and verified after readback.
- Explicit concurrency control for overlapping strategy/protection writers, with tested conflict behavior.
- Fail-closed handling for database outages, retries and ambiguous write outcomes.
- Reconciliation of Hyperliquid positions, ownership, pending claims, peaks and protective orders.
- End-to-end paper/testnet run plus controlled production rollout and rollback plan.

No live trading changes are included in this audit.
