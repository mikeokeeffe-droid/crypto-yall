# One bot per coin: original execution-path audit and safe cutover gate

**22 November 2026. Draft PR #42. Review only — no code execution, credential
access, exchange calls, trading or live workflow edits. Testnet/live NO-GO.**
Source inspection pinned to baseline commit
`2c7db8d03e47f33c65708d2d0519cbada6c93e25`.
This is a checkout/source audit, **not proof of what a separate older server
or deployed workflow is running**.

## Operator requirement — one owning bot per account/DEX/coin

Daily, Intraday and Aggressive **must not simultaneously trade/own the same
account, DEX and coin**. Different coins may be owned by different bots.
The only permitted same-coin additional entry **in the future architecture**
is an Aggressive pyramid on **Aggressive's already verified own parent
position**, subject to separately verified add count, risk and durable fence.
It is **not** a second bot's right to claim that coin.

A coin is unavailable to other bots from **before the first attempted send**
through pending, open, partial-fill, unknown-ACK, crashed/late response,
protection-only, and recovery states. Never infer release from a missing
position snapshot, local owned_coins set, alleged cancellation, or expired
Gist claim. The disposable review journal intentionally has **no release**;
production release is **unimplemented** and must require independent account-
wide orders/fills/position reconciliation and reviewed operator controls.

## Original checked-in direct-write paths — five, all still legacy

| Bot | Workflow and run entry | Original executor | Key exposure and observations |
| --- | --- | --- | --- |
| Daily | `.github/workflows/execute-trades.yml` runs `python hyperliquid_executor.py` (line 36) | `hyperliquid_executor.py` | One `HL_PRIVATE_KEY` injection (workflow line 55); `market_open` line 496; `market_close` lines 439/441; `update_leverage` line 491 |
| Intraday | `.github/workflows/execute-intraday.yml` invokes `intraday_profit_protection.py` for regular trading (line 78) **and** protection-only monitor (line 171) | Wrapper calls `intraday_executor.py` | Two signing-key injections (lines 97/185); `market_open` executor line 553; `market_close` lines 488/490; `update_leverage` line 548 |
| Aggressive | `.github/workflows/execute-aggressive.yml` invokes `aggressive_profit_protection.py` for regular trading (line 44) **and** protection-only monitor (line 144) | Wrapper calls `aggressive_executor.py` | Two signing-key injections (lines 66/161); `market_open` line 550; `market_close` lines 504/506; `update_leverage` line 545; pyramiding remains in its strategy |

The workflows use **three different concurrency groups**:
`execute-trades-live`, `execute-intraday-live`, and
`execute-aggressive-live` (their respective workflow lines 10–11).
That prevents overlap only within each workflow's group. It is **not**
an account/coin-wide lock across all three bots. The five invocations
include retry and long-lived protection-only loops; **all five** must
be accounted for before any coordinated cutover.

## Why the current source-level ownership filter is insufficient

The entry paths compute
`foreign_coins = set(open_positions.keys()) - owned_coins`
(Daily line 1252; Intraday line 807; Aggressive line 776) and filter
open/add candidates. Each relies on that bot's own persisted state/Gist
`owned_coins` and `pending_entry_claims`. The claim is written before the
legacy `execute_trade` call, but it is **not a shared atomic reservation**
across the three bots. Two workers can both read no current SOL position,
independently claim SOL, then each call `exchange.market_open` before
either has an observable fill. Separate workflow concurrency groups
do not prevent this time-of-check/time-of-use race.

Original executors directly construct/use signing-capable Hyperliquid
clients. They can still call `market_close(coin)` **without size**, and
each catches leverage-update errors before proceeding to `market_open`.
These are separately recorded release blockers; they must not be copied
as-is into the proposed sender.

## Review-only journal is already enforcing the intended reservation

The **disposable** `sender_review/ci_only_journal.sql` has primary key
`(environment, account, dex, coin)` for `scope_fences`; the record function
serializes account and scope claims and rejects any active nonce. Offline
tests verify one of three simultaneous same-coin claims succeeds and
others are held, including fresh nonces and an unknown-ACK with permanent
HOLD. This does **not** change original workflow behavior, implement a
live sender, authenticate a bot, or prove safe eventual release.

## Future integration: coordinated, independently reviewed — NOT implemented

1. **Inventory and freeze all five paths** plus manual/retry entrypoints and
   protection-only loops. Confirm the actual deployed hosts and credentials
   independently; checked-in source is not proof of host state.
2. Keep bot strategy, sizing, signals, profit protection, BTC/ETH market gate,
   and Aggressive's owned-position pyramid logic **unchanged**. Produce
   signer-free intent requests and independently authenticate which bot
   requested which action. Requests must not self-assert ownership.
3. A single protected coordinator resolves **server-fixed** network, account,
   DEX, coin and bot identity, verifies authoritative current full-account
   position/orders/fills and previous/legacy exposure, and atomically
   reserves the exact account/DEX/coin with a durable nonce, fence, CLOID
   and attempt record **before** any exchange write. If unavailable,
   incomplete, stale, contested or unknown, **HOLD** the coin.
4. Only one independently secured sender may use exchange trading keys.
   Bot workers and all five old paths must be demonstrably unable to sign
   or send, with runtime network/secret denial verified on the actual hosts.
   Reject a second bot's same-coin claim, including while first bot holds
   pending, partial, unknown-ACK, or protective-exit state. Different coins
   remain independently eligible when account-wide risk policy permits.
5. Handle Aggressive pyramid adds **only as the same verified owner under
   its existing reserved coin**, with parent/fill/size/side/add-budget
   checks. Do not allow a second reservation or infer a safe add from a
   local Gist flag alone.
6. Preserve **ongoing exchange-resident exit protection** and a rehearsed
   manual flatten/escalation process throughout cutover, outages and
   rollback. Never send an unsized/unauthenticated protective close.
   Unknown outcomes never trigger blind retry or automatic lock release.
7. Only after independent security/risk review, infrastructure attestation,
   operator-approved staged testnet work and a separate live go/no-go may
   a controlled coordinator replace all five old write paths. **No partial
   cutover and no rollback that reactivates two writers.**

**Disposition: SOURCE-ONLY VERIFIED LEGACY RISK; SINGLE-SENDER CUTOVER
UNIMPLEMENTED; PR #42 DRAFT; TESTNET/LIVE NO-GO.**
