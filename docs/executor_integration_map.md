# Executor integration mapping — review only

No live executor files have been edited by this pull request.

## Confirmed entry execution points

- Aggressive: `aggressive_executor.py` function `execute_trade`, `exchange.market_open` near line 544; trade dispatch near line 802.
- Intraday: `intraday_executor.py` function `execute_trade`, `exchange.market_open` near line 547; trade dispatch near line 832.
- Daily: **located** in `hyperliquid_executor.py`, function `execute_trade`, `exchange.market_open` near line 490; ownership and cross-bot checks in `main` near lines 1202–1251.

## Integration contract (not yet implemented)

1. Preserve all protection-only exit logic and do not block closes if Supabase is down.
2. Gate **every** opening or position-increasing path, not just strategy decisions.
3. Acquire reservation and durable intent in the same shared staging database, then re-read exchange positions and outstanding orders.
4. Submit only after all checks succeed; record unique client-order intent and reconcile exchange outcome.
5. Unknown exchange outcome must remain fenced until independently verified; a TTL alone is not enough.
6. A filled position requires durable ownership handoff; do not release a fence just because the HTTP response succeeded.
7. All three bots must use the same gate. Enabling only one bot while other bots can still open without it is unsafe.
8. Test on dry-run/mocks first; use a dedicated staging Supabase project; require explicit approval before any live change.

## Blockers

- The existing `executor_entry_dry_run_staging.py` is a standalone simulation, **not wired into live executors**.
- Real order/position reconciliation and durable owner handoff are not implemented.
- Daily's real entry module is identified; no executor has been modified.
- Staging Supabase project RPC deployment and privileges remain unverified.
