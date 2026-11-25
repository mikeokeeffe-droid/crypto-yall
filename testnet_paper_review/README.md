# Hyperliquid TESTNET paper trading activation — draft NO-GO preflight

**State: HOLD. No key use, no order placement, no deployment, no service activation.**

Scope: prepare a *separate*, manually approved, one-order-at-most **Testnet-only** trading experiment, not simultaneous activation of Daily, Intraday, and Aggressive, not an update to their GitHub Actions workflows, and never Mainnet.

## Current evidence

- Live read-only public `POST https://api.hyperliquid-testnet.xyz/info` from Windows and a transient restricted Hetzner account succeeded for `clearinghouseState` and `openOrders`.
- Latest Hetzner public account state showed `assetPositions: []`, no open orders, and `marginSummary.accountValue: "0.0"`, `withdrawable: "0.0"`. **This does not establish sufficient Testnet trading collateral.**
- The existing three executors use exchange trading methods including `market_open`, `market_close` and `update_leverage` and route their API through the `HL_TESTNET` variable. Existing workflow files receive `HL_PRIVATE_KEY`. These **must not** be reused directly for the initial paper trading cutover.
- Draft PR #40 documents existing shared-account order race risks, and draft PRs #41, #42, #45 are not a completed, independently reviewed trading gateway and exclusive signer.

## Before any order is enabled (all currently UNVERIFIED)

1. Verify the exact Testnet public account has mock USDC available for perpetuals without using or transmitting real funds for this experiment; do not assume token availability from a 0-balance response.
2. Use a **separate, Testnet-only trading agent/key**, with strictly Testnet-scoped authorization, never shared with Mainnet or existing bot runners. Never paste a secret into chat, logs, PRs, shell history or terminal screenshots.
3. Build and independently review a separate order sender with a hard-coded, unchangeable Testnet endpoint and an unconditional Mainnet abort. No fallback to a Mainnet URL, credentials or signer.
4. Require a one-shot manual authorization, explicit operator approval for the exact reviewed executable/version, max **one** small order, fixed symbol/direction, capped notional, capped leverage, defined loss/stop handling, timeout, and an immediately accessible halt control.
5. Verify single-writer/position ownership, duplicate request protection, unknown-ack recovery, exact order reconciliation and reduce-only/cancel handling. An uncertain exchange response must **never** cause a blind retry.
6. Enforce host-level service isolation, no production database/state changes, no alternate credentials, and reviewed network restrictions. Keep old PR #41 collector inactive and avoid changes to existing three trading workflows.
7. Test no-key offline failure cases, one-time permission expiration, restart/replay, duplicate/cross-bot positions, missing funds, and all Mainnet failure paths. Collect reviewed CI evidence.
8. Obtain independent security review, then a separate **explicit** human authorization immediately before the first Testnet order. After the run, verify order and position state through a separate read-only query and leave the new order sender disabled.

The profile in `paper_activation_hold_profile.json` is a static **HOLD** contract, not an enablement switch. `offline_paper_preflight.py` exits 2 and makes no API, wallet, network or GitHub secret requests. All tests are offline and have no side effects.

## Testnet mock USDC

Official docs: https://hyperliquid.gitbook.io/hyperliquid-docs/onboarding/testnet-faucet

The faucet may require the **same address to have previously deposited on Mainnet**; eligibility and current balances must be verified in the official interface. Official Testnet faucet: https://app.hyperliquid-testnet.xyz/drip. Do **not** make a Mainnet deposit merely to satisfy a test requirement without a separate deliberate decision, since that would involve real funds.

## Operator decision

No trading authorization has been given for any specific executable, signer, symbol, size, or order yet. A general request to prepare for Testnet paper trading is authorization to review and draft only. **NO-GO for order placement.**
