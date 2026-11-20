# PR #40 — order identity and reconciler acceptance contract

**5 November 2026 — DESIGN / NO-GO / draft only.** This is a detailed, reviewable contract for the original Daily, Intraday and Aggressive bots on one Hyperliquid account. It adds no live code, trading orders, keys, privileged DB writes, migrations or network reads. Existing strategies, signal thresholds, TP/SL and kill-switch behavior remain unchanged.

## Why this contract is needed

In the original three executors, `pending_entry_claims` stores a coin, direction and timestamp, then `market_open` sends an order. On restart each bot can adopt a same-direction position as its own without independently verifying the underlying order. `foreign_coins = open_positions - owned_coins` is a non-atomic observation. Close calls also retain an unsized `market_close` fallback. See `docs/pr40-original-executor-ownership-boundary-audit-20261105.md`.

The current disposable PostgreSQL tests prove only that **synthetic** concurrent claims and atomic pre-submit intents behave correctly. They neither link a verified client order identifier to Hyperliquid nor authenticate full account activity.

## Design invariants: must hold at every live submission boundary

1. **Pinned scope**: `environment + effective_account + perp_dex + coin`, determined from an independently reviewed operator configuration, not the API-agent signer address, caller's JSON or local Gist state. Only the default perp DEX is covered by present CI experiments. Reject any unrecognised scope.
2. **Authenticated executor**: dedicated credential/role identifies Daily, Intraday or Aggressive; the service validates that identity independently of supplied `bot` text. Restrict database writes and claiming another bot's token.
3. **One outstanding intent per exact scope**: a single atomic transaction creates the durable claim and pre-submit intent with account, bot, side, exact decimal quantity, unique request UUID and monotonic fence. An unresolved intent blocks all three bots. A TTL does **not** authorize reassigning or deleting it.
4. **Separate client order identifier**: generate an opaque unique 128-bit CLOID and persist it immutably in the *same* authorized pre-submit transaction. Do **not** treat a predictable CLOID derived from a claim token as authentication. The CLOID is a correlation identifier, not an access token, exchange proof or replay permission. Verify that the pinned SDK's actual order method supports passing the CLOID **before** proposing integration; do not assume `market_open` has this capability.
5. **Real submission occurs only after durable commit**: only the authenticated bot with the still-current fence may prepare/dispatch the exact intended order. The real exchange request must contain the precommitted CLOID, scope, side, size and intended reduce-only semantics. A stale process must fail closed at the final submit boundary, not merely at signal generation.
6. **Unknown outcomes stay unresolved**: on timeout, connection error, malformed reply, crash, partial fill, state-save error, rate limit or missing OID, keep the claim as pending/uncertain. Do not retry with the same or a new CLOID until independent reconciliation resolves it. Do not automatically adopt a same-side exchange position.
7. **Read-only reconciliation never owns the exchange**: separately reviewed collector with no trading signer, exchange write method or state-changing DB privileges; fixed HTTPS `/info` host and pinned account. Capture request type, account, DEX, original `oid`/`cloid`, time bounds, HTTP/TLS result, raw response hash and capture clock outside the response JSON. Public account queries do **not** authenticate control of that wallet.
8. **Full account history required**: establish CLOID-to-OID mapping from a trusted pre-submit intent to independently captured order status, then unique `oid`-to-`tid` fills, *all* account activity affecting the coin, open orders and fresh position state. No missing interval, saturated 2,000-result page, 10,000-result retention uncertainty, same-millisecond skip, duplicate fill, manual/other-bot netting, liquidation or unexplained delta can be ignored.
9. **Close authorization is an entirely separate reviewed operation**: no close because a synthetic evidence checker returned `parsed_untrusted`, `review_only` or `handoff_candidate`. Require an atomic revalidation of bot-attributed, still-open quantity and current fence immediately before a specified-size, reduce-only close: `0 < requested_close <= bot_reconciled_remaining <= fresh_same-side_account_position`. Never fallback to `market_close(coin)` without explicit quantity.
10. **Crash consistency and ledger audit**: store immutable audit records for creation, attempted dispatch, exchange observations, partial fills, unresolved outcomes, reconciliation decision and every approved position-size change. A separately privileged reconciler performs a fenced compare-and-swap; an executor may not resolve its own ambiguous claim.

## Minimal future intent fields (schema contract, not migration)

| Attribute | Source / guarantee |
| --- | --- |
| `environment, effective_account, dex, coin` | Pinned effective account and approved market scope |
| `bot_id` | Independently authenticated dedicated executor identity |
| `intent_token, fence_token` | DB-issued unique UUID and monotonic DB fence |
| `action, direction, requested_size` | Immutable exact intended trade; numeric decimal, positive, no float-based inference |
| `cloid` | Separately generated opaque 16-byte correlation identifier, unique and recorded **before** any dispatch |
| `pre_submit_baseline_ref` | Immutable account-position/open-order capture preceding submission; absent baseline = HOLD |
| `dispatch_phase` | Durable `reserved -> prepared -> dispatch_unknown -> observed` state; unknown cannot silently return to available |
| `oid, fill_ids, filled_size` | Independently observed exchange references **after** submission; never guessed at creation |
| `evidence_capture_refs` | Append-only reference to independently collected request/response records, scoped and time-bound |
| `reconciliation_state` | `HOLD` by default; only a separately approved fenced reconciler may finalize |

Status names above are proposed; they are **not** existing PostgreSQL types. Neither `cloid` nor `oid` alone proves bot ownership.

## Failure and acceptance scenarios

| Event | Required result |
| --- | --- |
| Daily and Intraday enter SOL at same instant | Exactly one pre-submit reservation, loser never dispatches |
| One bot hits a different approved account | Separate reservation key; cannot read another account's claim |
| Bot replays request token/CLOID or impersonates a peer | Reject; no second order |
| Crash after durable intent but before dispatch | Keep unresolved until independently proven not sent; no automatic release |
| Crash/timeout after submission but before OID persisted | Query by precommitted CLOID; if order state or history incomplete, HOLD |
| Fills partly complete or status changes between reads | HOLD and preserve per-fill evidence |
| Manual same-side trade appears during bot recovery | Do **not** adopt position using direction; ownership cannot be inferred |
| Other bot/manual opposite-side trade nets a position | HOLD; reconcile account-wide delta, not just a local bot ledger |
| Fills history reaches cap or has missing timestamp ties | HOLD; do not claim complete coverage |
| Stale worker attempts to send order after later fence | Reject at final dispatch boundary |
| A normal TP/SL wants to close during HOLD | Never submit an unverified close; separately approve operational fallback strategy before changing live protection behavior |
| Existing legacy positions lack trusted pre-submit evidence | Do not backfill bot ownership from coin alone; quarantine for explicit operator reconciliation and controlled migration |

## Staged integration and release gates

**Gate A — CI and code review:** all four PR checks pass; disposable database test proves account scoped lock + immutable CLOID intent + privilege restrictions + restart/fault cases. The blocked CLOID SQL modification is **not** implemented and must not be bypassed.

**Gate B — isolated read-only provenance:** independently security-reviewed capture component and audit store, unit and fault tests using captured *non-sensitive* fixtures, complete coverage policies; no live API call without separate approval.

**Gate C — coordinated testnet dry run:** explicit approval; all three bots must be connected consistently to the same approved account-scoped coordinator *before* testing shared locking. A one-bot-only rollout would leave the other two trading outside the lock, so is insufficient. Preserve strategy signals and record latency/timeout behavior.

**Gate D — separate production approval:** operator reviews ownership of existing positions, prepared roll-forward/back migration plan, manual trading risk, failed-close behavior and kill-switch semantics; approves every affected executor/workflow/DB privilege change. **Do not promote PR #40 as it stands.**

## Official API source boundaries

- Hyperliquid `POST /info` `orderStatus` looks up an order by OID or a 16-byte hexadecimal CLOID: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- The `/exchange` order payload accepts an *optional* 128-bit hexadecimal CLOID; this does **not** establish SDK 0.24.0 API compatibility automatically: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint
- Fill history and rate limits require bounded collection and review: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits

**No-Go conclusion:** the missing independently trusted submission path, capture/reconciler, and legacy-position migration prevent safe live release. Keep the original bot files unchanged and PR #40 draft.
