# Daily executor safety review — 2026-11-25

**Status: HOLD / REVIEW ONLY.** This report inspects the original Daily executor on `main`. It does not authorize merging, executing a workflow, deploying an order sender, using keys, touching Hetzner, or trading on Testnet or Mainnet.

## Scope and verified facts
- `hyperliquid_executor.py` is the original Daily executor. Its `execute_trade` is exercised through a fake exchange in draft PR #46's offline-only rehearsal; that proves limited behavior with mocks, not safe actual exchange operation.
- `.github/workflows/execute-trades.yml` invokes `python hyperliquid_executor.py` with original `HL_PRIVATE_KEY`, `HL_ACCOUNT_ADDRESS`, and repository variable `HL_TESTNET`. It has manual/API dispatch and a separate report-writing step. Do not dispatch this workflow as a Testnet experiment.
- Independent Testnet-only credential-verification workflow #45561480906 succeeded. It verified key derivation and a read-only agent association, not order permissions, Testnet collateral, position ownership, or full execution safety.

## Blocking observations in original executor

1. **Dangerous environment selection / fail-open halt** (`get_client` around lines 187-202, `check_kill_switch` around 798-800; `execute-trades.yml` environment): only `HL_TESTNET=true` selects Testnet; an empty, malformed or false value selects Mainnet. The existing workflow passes a variable that could be empty. The kill switch halts only when its value is exactly `OFF` (case-insensitive); an unset value defaults to `ON` (trading enabled). A new Testnet experiment must never reuse these variable-driven paths or any Mainnet-capable identity.

2. **Unknown acknowledgment can release a claim** (`main` around lines 1275-1296): the code writes a pending entry claim before sending an open order but removes it whenever `result.status != "filled"`. Unknown/error parsing or transport uncertainty does not prove non-execution. A successful exchange fill with missing acknowledgment could later be mistaken for another bot's position; do not blindly retry or release claims. Require durable one-shot intent + immutable request ID + read-only reconciliation and operator HOLD for ambiguous acknowledgments.

3. **Ownership recovery isn't a verified exclusive lease** (`main` around 1205-1258): a matching coin and side can promote a pending entry claim to ownership without a verified unique fill/order identity. Filtering foreign coins based on a single pre-trade position snapshot is not a cross-process atomic lock. Require an exclusive writer, durable idempotency/claim lease, and reconciled exchange fills before entries or closes.

4. **Close can target whole account position** (`execute_trade` around 436-443): when `close_size` is zero or missing, `market_close(coin)` is called without an explicit size. A safe trial sender must reject unbounded close requests, use an independently verified owned size, and enforce a reviewed reduce-only exit/cancel path.

5. **Risk caps need a new independent enforcement boundary** (`execute_trade` around 445-501; `check_daily_drawdown` around 803-867): Testnet minimum-order behavior can raise notional to $12 even when the strategy calculates less. The drawdown guard is run-level accounting, not a guaranteed exchange-side stop. A separate Testnet sender needs a hard one-order maximum, fixed symbol/side, strict total-notional and leverage ceilings, measured fill/remaining exposure, timeout and emergency halt—irrespective of strategy outputs.

## Required acceptance checks before an actual order
- Hardcoded Testnet base URL, no Mainnet import/fallback, no original `HL_PRIVATE_KEY` or original main account secrets; host/network deny where feasible.
- Separate Testnet-only signing identity with exact owner, role, scope, expiry, and permissions independently verified. Never publish secrets or private key output.
- Fail closed for missing/invalid environment, kill controls, limits, wallet identity, balance, state storage or network response.
- No order without a unique persist-before-submit request, exclusive account/coin ownership, read-only preflight and explicit authorization for exact artifact, symbol, side, notional and leverage.
- Negative tests for concurrency, replay, restart, delayed/ambiguous ack, partial fill, stale snapshot, foreign position, excess size, stale price, close-size mismatch and Mainnet/fallback.
- Independent security review of code and runtime, separate approval for eventual single Testnet-only manual order, verified fill/position reconciliation after that order, with sender disabled afterward.

## Decision

**HOLD.** Continue with no-key, no-network offline review/tests on draft PR #46. Do not merge it or activate trading based on green CI. Existing Mainnet and all three original bots remain unchanged by this review.
