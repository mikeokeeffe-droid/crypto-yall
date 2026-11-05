# PR #40 — independent ownership evidence for shared-account closes

**Status: DESIGN ONLY / NO-GO.** This document does not approve enabling orders, releasing a claim, modifying original executors, using production credentials, or merging the draft PR.

## Why matching fills still do not establish bot ownership

Daily, Intraday and Aggressive operate on one Hyperliquid account. Hyperliquid provides account-level order, fill and position records, not a trusted `bot=daily` field. A `bot` string in a local file or synthetic fixture is self-asserted. Matching coin, side, quantity or an order ID from that same file is **not** independently authenticated bot-to-order attribution. An effective account address can also differ from an agent wallet; subaccounts, vaults and non-default perp DEXes must not be silently conflated.

The current offline reviews intentionally return only `hold`, `review_only`, `parsed_untrusted` or `handoff_candidate`. None may be used as authorization to submit a close, clear a pending claim or set `owned_coins`.

## Required durable trust chain (not implemented)

1. **Independent account scope:** Pin mainnet/testnet, effective account address, default perp DEX and any vault/subaccount choice from reviewed configuration. Reject mismatched account, wallet or DEX; never infer the trading account from an API-agent address.
2. **Pre-submission bot identity:** Authenticate the invoking bot independently of an input `bot` string. Acquire a **shared, atomic, fenced** per-account/per-coin intent lock; persist immutable bot ID, account, DEX, coin, intended side, exact size, request UUID, monotonically fenced token and creation timestamp **before** any order can be sent. Preserve uncertain outcomes; never auto-expire/reassign an ambiguous claim.
3. **Order identity:** Bind the trusted persisted intent to the actual exchange order ID (`oid`) and, where supported, a client order ID (`cloid`), with explicit durable lifecycle transitions. A post-hoc `oid` typed into bot state is not proof of who submitted the order. Timeouts and unknown submission outcomes remain unresolved until reconciled.
4. **Read-only exchange evidence:** An independently reviewed, *non-trading* collector would query pinned Hyperliquid `POST /info` endpoints for `orderStatus`, unaggregated `userFillsByTime`, `openOrders` and the relevant clearinghouse position state. Preserve request scope, response bytes, HTTP/TLS outcome, capture time, identifiers and error state in an append-only audit trail; reject redirects, untrusted origin, mismatched identities, missing intervals and staleness. No wallet signing is needed for these account-information queries.
5. **History coverage:** Join `oid`, fill trade IDs and size/side/timestamps against the trusted intent. The official `userFillsByTime` endpoint returns **at most 2,000 fills per response** and makes **only the latest 10,000 fills** available; this cannot certify full history by itself. Persist lossless checkpoints from a controlled collection process, detect gaps/retention risk, reject saturated windows and account for duplicate or partially filled orders. Do not treat an empty/short page as absence of fills.
6. **Account-wide netting:** Reconcile *all* fills and relevant changes (other bots, manual actions, liquidations and external account activity) against position snapshots and pending orders. Opposite-side orders can reduce a shared position. If any competing order, unexplained delta or ownership overlap exists, **HOLD**. Do not attribute a netted exchange position from local `owned_coins` sets.
7. **Safe close-size bound:** After independently verified and fully covered history, require `0 < close_size <= bot_attributed_unclosed_size <= live_exchange_position_size` on the same account/DEX/coin/direction, with a fresh authoritative position snapshot and atomic lock immediately before submission. **Never fall back to an unsized `market_close` on uncertainty.** Still do not authorize through the offline review module.
8. **Post-close reconciliation:** Account for partial executions, cancels, rejects, unknown outcomes, repeated requests, fees and subsequent snapshots. Only an approved coordinator may atomically update durable ownership and release a fence after independent reconciliation; never use an individual GitHub Actions run, local Gist snapshot or a caller-provided boolean as sufficient proof.

## Explicit blocking conditions

- Account, DEX, bot identity or order mapping missing/mismatched; order submitted without a pre-existing durable intent.
- Duplicate, orphaned, late or missing fills; unsized close; incorrect direction; negative/oversized bot quantity.
- Incomplete account history, API retention cutoff, saturated fill page, unknown order outcome, unobserved manual trade or position discrepancy.
- A stale snapshot, uncertain timestamp/order sequencing, another bot's same-coin intent, or a failed/expired fencing attempt.
- A simulated `authenticated`, `tls_verified`, `transport_verified`, `fills_complete` or `position_owned` field without independent provenance.

**Default outcome for any condition above: HOLD; investigate manually.** There is no safe automatic override in PR #40.

## Controlled implementation order

1. Review and test the identity/atomic-intent database design, privileges, failure modes and idempotency **without production credentials**.
2. Implement a separate **read-only capture client**, initially in testnet or with synthetic inputs. Keep it disconnected from trading executors; use no signing keys and no `exchange` endpoints.
3. Review raw `orderStatus`, `userFillsByTime`, `openOrders` and account position fixtures with truncation, netting, liquidations, restarts, concurrent bot orders and adversarial-origin tests.
4. Prove checkpoint coverage and account-wide reconciliation independently; enforce per-bot quantity as a ceiling, with independent review of the data store and all privilege boundaries.
5. Require a second explicit production change review, testnet validation and user approval before proposing *any* change to the original three live executors, runtime workflows, secrets or deployment.

## Source references

- Hyperliquid info endpoints (including order status, unaggregated user fills and their documented limits): https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- Hyperliquid perp account state: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals
- API rate limits: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits
- Existing pinned SDK 0.24.0 close-source review: `docs/pr40-sdk-0240-close-source-review.md`

**Not implemented:** a trusted authenticated capture service, append-only collector, shared atomic intent database with verified bot identity, production-safe reconciler or live close adapter. No existing offline pass is a production go-ahead.
