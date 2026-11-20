# PR #40 — precise original-executor ownership boundary audit (5 Nov 2026)

**Review only — NOT deployment approval.** Examined the original `main` executors and Hyperliquid's published `/info` contract. This document does not modify executors, workflows, Gist state, production DB, exchange positions, secrets, or settings. Draft PR remains **NO-GO**.

## Observed original code — preserve strategies

| Executor | Persisted pre-order claim | Same-coin check | Restart recovery | Actual entry call | Close risk |
|---|---|---|---|---|---|
| Daily, `hyperliquid_executor.py` | 1275–1294 | 1248–1258 | 1205–1225 | 432–498 | 436–443 |
| Intraday, `intraday_executor.py` | 829–847 | 803–817 | 743–769 | 476–553 | 485–492 |
| Aggressive, `aggressive_executor.py` | 796–812 | 773–782 | 701–721 | 499–550 | 501–508 |

File/line references are to original `main` as inspected Nov 5, not merged changes.

- The current `foreign_coins = open_positions - owned_coins` gate is based on an exchange snapshot and each bot's separate local state. Two bots can both observe an absent coin, then submit concurrently. Keep the gate as an additional observation, but do not mistake it for an atomic account-wide reservation.
- Each bot saves `pending_entry_claims` with side and creation time before submitting, but without a DB-enforced, account-scoped claim tied to that exact exchange submission. Current pending-claim recovery can add a coin to `owned_coins` by checking that a visible account-level position has the same **side**. This alone does **not** establish which bot opened it. In particular, it could wrongly adopt a manual or another bot's same-side fill.
- Each executor clears a pending claim when the returned status is not `filled`. That includes potentially ambiguous/unknown submission outcomes. Any future durable coordinator must preserve an unresolved claim until independently reconciled.
- Direct `exchange.market_open(...)` calls are present; no `cloid` in the three original files. A post-fill `oid` may be parsed, but a post-hoc match is not independent proof of submission ownership.
- The close paths still contain `exchange.market_close(coin)` **without explicit quantity** when `close_size <= 0`. A new review must never approve this as a bot-owned close; sizing must not exceed independently reconciled bot-attributed amount or current exchange position.
- Aggressive pyramiding and existing signal/TP/SL strategy rules must not be changed by this review.

## Verified Hyperliquid API facts

Official `POST /info` supports `orderStatus`, queried with the actual **master/subaccount effective address** and `oid` as exchange numeric order ID or **16-byte client order ID (cloid) hex string**. Order status and historical orders can expose `oid`/`cloid`; fills expose `oid` and `tid`. No documented exchange fill field authenticates `bot=daily/intraday/aggressive`. Public info queries require no wallet signing, so data retrieval is **not** proof of wallet control.

`userFillsByTime` has at most 2,000 fills per response and access to only the latest 10,000. Inclusive timestamp boundaries, same-millisecond fill ties, position netting, account-scope mismatch, and missing archive history must all keep an ownership decision on **HOLD**. Read-only responses cannot substitute for durable trusted submission lineage.

Sources:
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits

## Exact remaining implementation boundaries, in order

1. **Independent bot identity and account-scoped admission before any order**. Preserve the existing signal decision; require a shared, atomic, durable claim for `environment + effective account + DEX + coin` tied to the approved invoking bot. Pre-submit record needs exact direction, requested quantity, unique request token, monotonic fence, and exchange client order identifier. A matching database row alone never authorizes action. Offline disposable PostgreSQL models demonstrate concurrency only; no live adapter exists.
2. **Safe pre-submit baseline, order-submission identity and unknown-outcome durability**. A future separately reviewed integration must persist a trusted account position/open-order baseline and unique CLOID *before* order dispatch. After dispatch, associate returned OID and lifecycle with that exact intent without trusting mutable bot input. If save/HTTP/order response is uncertain, retain lock and block re-entry and automatic adoption.
3. **Independent read-only evidence capture and reconciliation**. A separately reviewed reader with pinned account/environment/DEX and fixed Hyperliquid `/info` host obtains `orderStatus` via original CLOID/OID, `userFillsByTime` unaggregated, open orders, and clearinghouse position snapshots. Verify transport provenance, bounded windows, complete archived coverage, all same-coin account activity (including manual orders), and exact OID-to-fill mapping; reject duplicates and partial/unknown outcomes. No signer, live SDK exchange client, production DB write or order execution inside reader.
4. **Safe close permission separate from evidence checks**. Only an independently authorised fenced reconciler can attribute remaining size to a bot. Any close sizing must satisfy `0 < close_size <= bot_attributed_size <= fresh_account_position_size` and be tied to the same side, coin, account, DEX and latest fence; no fallback to unbounded market close. Existing protective exits require an explicit policy for how to behave during HOLD; no silent bypass or strategy change.
5. **Adversarial and recovery tests before live proposal**. Test two simultaneous bots, same-side manual trades, netting/opposite side, partial fills, restart after submission but before state save, stale worker, repeated cloid/order ID, expired reservation with durable intent, history cap and incomplete page, delayed/failed HTTP, collateral liquidation, API-agent versus effective-account mismatch, and no incorrect close. Testnet and explicit second production review/approval come last.

## Current blocker and operator decisions

The proposed CI-only SQL change to persist a CLOID was blocked by repository safety checks and **was not applied**. Do not attempt to circumvent that block by another write route. PR #40's existing draft tests remain useful but cannot establish live trade ownership.

**No-Go remains in force.** Do not merge, deploy, execute tests with a real trading wallet, alter live workflows, release production claims, change the original strategy or override kill-switch behavior. Any actual migration/integration requires a separate explicit review and approval.
