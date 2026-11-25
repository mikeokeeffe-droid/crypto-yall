# Original Crypto Y'all bot restart evidence — 2026-11-25

**Read-only review only; NO TESTNET TRADING RESTART AUTHORIZED.** Do not change original 3 workflows, Gist state, global `HL_TESTNET`, Mainnet or Hetzner services merely because these files pass CI.

## Verified GitHub history

| Bot | Last observed run | Status | Evidence |
|---|---|---|---|
| Daily (`execute-trades.yml`) | 2026-10-24 00:15 UTC | Success, **HL_TESTNET=false**, **KILL_SWITCH=on**, zero planned trades | https://github.com/mikeokeeffe-droid/crypto-yall/actions/runs/40044074650 |
| Aggressive (`execute-aggressive.yml`) | 2026-10-24 13:02 UTC | Cancelled; last inspected 2026-10-23 failed | https://github.com/mikeokeeffe-droid/crypto-yall/actions/runs/40096422121 |
| Intraday (`execute-intraday.yml`) | 2026-11-07 00:07 UTC | Cancelled; last inspected 2026-11-06 run succeeded but **HL_TESTNET=false**, **INTRADAY_KILL_SWITCH=off**, no order placement | https://github.com/mikeokeeffe-droid/crypto-yall/actions/runs/42316237705 |

Last successful Intraday evidence: https://github.com/mikeokeeffe-droid/crypto-yall/actions/runs/42309672826 . Its long-running protection loop kept reporting that the kill switch was OFF and halting.

Last inspected failed Aggressive run: https://github.com/mikeokeeffe-droid/crypto-yall/actions/runs/40016079250 . Its Gist save returned HTTP 403 with **API rate limit exceeded** in the server's own response. This is **not** evidence of a bad Testnet wallet key, nor proof that the issue is still occurring. The high-frequency workflow can exhaust Gist API quotas and must have durable, tested shared state before restarting.

In `main`, original Daily, Intraday and Aggressive workflows are **manual `workflow_dispatch`**; their historic hourly/half-hourly/daily dispatches were triggered outside those workflow YAMLs. The historical schedule source and why dispatch stopped are **not yet established**; cancellations alone do not prove the cause. Their current repository variables and encrypted secrets are not readable with the available GitHub connection. Their last logged value must not be mistaken for current live configuration.

The old executors have an environment-selected endpoint:
`HL_TESTNET=true` uses the Testnet API, while `HL_TESTNET=false` selects **Mainnet**.
Existing workflows receive `HL_PRIVATE_KEY` and exchange order methods. Switching a shared variable or dispatching an original workflow without verifying all inputs could place Mainnet orders. Do not trigger old `Test Trade`: it directly opens and closes BTC on Testnet and is not a harmless diagnostic.

## Verified Testnet account evidence (user-supplied screens + one-shot checks)

- Public Testnet account `0xF14348Bdf59BA186F9CdD0fC5F369e1f6D3b7dC0`.
- Local Testnet interface on 2026-11-25 displayed approx **1,003.488794 USDC available**, **$1,003.49 trading equity**, and **0 open positions**. These displays supersede earlier `0` account margin observed using read-only API; verify fresh API state before trading.
- Hetzner restricted `readonlycheck` with transient `IPAddressDeny=any` + selected IP allowed successfully fetched **read-only** Testnet public `clearinghouseState` and `openOrders` (user confirmed `[]` for orders).
- Existing Hyperliquid Testnet API-wallet entry is visible in UI, but its association to the GitHub signing secret, scope and expiry are **not verified**. Do not overwrite keys or expose signing secrets to chat/terminal/screenshots.

## Mandatory sequence to restore trading

1. Operator inspects **GitHub Settings → Secrets and variables → Actions → Variables** for `HL_TESTNET`, `KILL_SWITCH`, `INTRADAY_KILL_SWITCH`, `AGGRESSIVE_KILL_SWITCH` and shares **variable values only** (not secret keys or full secret values). **Do not edit variables** at this stage.
2. Audit existing scheduler/dispatch source, all three state Gists and bot ownership ledger; avoid Gist rate-limit recurrence. Avoid assuming a successful GitHub Action means an order happened.
3. Verify if an already-authorized, strictly Testnet-only signing agent can be safely reused. If not, arrange separate Testnet-only agent entirely outside chat, without altering existing Mainnet credentials.
4. Review one isolated, hard-coded-Testnet, single-bot order path, with exclusive sender, no blind retry, no Mainnet fallback, notional/leverage caps, deliberate position exit, and emergency halt. PRs #38/#40/#41/#42/#45/#46 are draft/unmerged; passing offline CI is not operational deployment approval.
5. Perform signed **dry-run/no-order** checks under isolated credentials and controlled network before any real Testnet order.
6. Only after independent approval and final observed state, request **explicit approval for exact Testnet order** (symbol, side, size, leverage, maximum exposure, stop/cancel behavior), then verify actual fills and leave automation disabled pending decision on further rollout.

**Current decision: HOLD. No trades, deployment, global variable changes, or workflow dispatch performed by this review.**
