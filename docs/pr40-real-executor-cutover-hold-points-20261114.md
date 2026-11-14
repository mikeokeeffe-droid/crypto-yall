# PR #40 — original-executor cutover hold points and evidence checklist

**Draft architecture review — 14 November 2026 — LIVE NO-GO.** This is a source-grounded implementation sequence, not approval to edit live bot executors, GitHub Actions secrets, server state or exchange accounts. None of the gates below is a completed production proof.

## Source findings checked on PR #40 at `9896236bf06c627a69c4867fd3246bc8163214b4`

| Original executor | Signer dependency | Mutating code path | Missing safety gate |
| --- | --- | --- | --- |
| Daily — `hyperliquid_executor.py` | Imports `Account`, `Exchange`; `get_client()` builds signer-backed Exchange | `execute_trade()`: `update_leverage`, `market_open`, both sized and **unsized** `market_close` branches | No signer-free initialization, leverage failure continues to market_open, no bounded provenance-backed close |
| Intraday — `intraday_executor.py` | Imports Daily's `get_client`, including its signer dependency | `execute_trade()`: same direct mutations and unsized close fallback | Same risks; must preserve current Intraday signal and profit protection precedence |
| Aggressive — `aggressive_executor.py` | Imports Daily's `get_client` | `execute_trade()`: same mutations, plus pyramid actions through `market_open` | Pyramids must be separately authorized against verifiable bot-owned existing exposure; closes still unsized when `close_size` absent |

**Important:** The original function may warn when `update_leverage` fails, then still call `market_open`. A request-only V2 draft records *desired* leverage and size, not exchange-confirmed leverage. Green offline CI proves only the disposable fixtures.

## Required atomic change boundaries

1. **Independent read-only bootstrap.** Design a separate Info-only client creation path that cannot import `get_client()`, `eth_account.Account` or `hyperliquid.exchange.Exchange`. Every original helper that needs Info/account data must be inventoried; preserve signal inputs and the real read-only operating mode before changing any strategy. Do not merely move `HL_PRIVATE_KEY` to a new environment variable.
2. **Remove bot-side write capability in one reviewed, coordinated cutover.** No Direct `market_open`, `market_close`, `update_leverage`, generic SDK order methods, alternate wallet/key imports, or fallback to old `get_client()` may remain reachable in any of the three workloads. A request-only socket response must not be interpreted as submission permission.
3. **Make coordinator the exclusive signing boundary.** Separately protected service account owns the signer and outbound order API. Three individually authenticated bot service identities can reach only a constrained local intent endpoint; none can read the signing key, sender state, write-capable SQL credentials or an alternate order proxy. Explicit deny/egress and secret-mount checks must be proven at the final deployment identity, not only temporary root CI UIDs.
4. **Durable account/coin serialization before dispatch.** Bind bot identity, account, environment, DEX, action, rounded size, requested leverage, margin mode, immutable request ID, CLOID and fencing token before any signing attempt. Persist an uncertain-send marker and never automatically replay ambiguous attempts. Verify the independent journal is not writable by bots.
5. **Leverage outcome must be proven, not assumed.** Do not open or pyramid after an unsuccessful, unknown or unconfirmed leverage operation. Future coordinator-side leverage policy and acknowledgements require an explicit risk review; the V2 `review_entry_leverage_v2` request is not a dispatch protocol.
6. **Separate close protocol and existing-position plan.** No unsized `market_close(coin)` fallback. Permit only independently reconciled, explicitly bounded, reduce-only size attributable to this bot's proven own position contribution. Manual trades, another bot's fills, stale data, opposite-side activity, incomplete paginated history or unclear exchange result imply HOLD and human recovery. Never silently convert a protective exit into a no-op in a deployed live bot; risk owners must approve an emergency protective close/STOP procedure first.
7. **No independent bot deployment.** Feature flags, workflow changes, secret revocation, and rollback must be reviewed as a coordinated account-level change to all three original bot processes. The old signer-capable workflows and a new coordinator must not overlap. After rollback, unresolved journal entries remain locked until independently reconciled.

## Required negative acceptance evidence (before any deployment decision)

- Static and runtime import/secret checks on **each actual bot executable**, including helpers and child processes, prove no usable signer/SDK mutation route or trading credential in the bot environment.
- A malicious or compromised bot identity cannot impersonate another bot, select another account/environment, view writer credentials, or submit commands outside the allowlisted entry schema. Distinct real service UIDs must be tested and independently reviewed.
- A coordinator outage, SQL failure, uncommitted journal entry, duplicated request, stale fence, lost ACK, crash after send, or network partition cannot cause a second write attempt; all order outcomes remain unverified until independent evidence resolves them.
- Attempts to request pyramiding, leverage changes and protective closes without the specifically approved ownership/reconciliation evidence fail closed. No assertion such as `submit_authorized=true` from the client grants authority.
- Exchange read-only order/fill/current-position reconciliation must account for partial fills, cancel/replace, funding/fees where relevant, manual positions and the complete period since the bot's last independently verified state. Missing history is **unknown**, not an empty position.
- Before enabling any live runtime, a reviewed rollback and emergency handling plan must preserve protective exits and be rehearsed without real orders; obtain explicit independent security/trading-risk signoff.

## Current state and next engineering review

**Completed only in disposable CI:** synthetic Info + source-extracted sizing, V1 and V2 request-only socket paths, distinct temporary Linux UIDs, coordinator-only disposable PostgreSQL roles, durable review journals, replay/restart checks and no-authority responses.

**Still not done:** actual three-executor signer-free bootstrap; credential removal from the real workflow/service process identities; exclusive real single-writer signing service; authoritative Hyperliquid order/fill provenance; safe bounded reduce-only exits; emergency operational coverage; audited staged rollout/rollback.

**Next code-review change should be a deliberately disabled, isolated implementation diff for the original read-only bootstrap with explicit import and credential-negative tests.** It must not be merged or deployed as part of this document change. Keep original trading behavior unchanged until all coordinated cutover and protective-exit requirements are accepted.

**Decision: PR #40 DRAFT — LIVE NO-GO.**


## 14 November 2026 — read-only exchange-history prerequisite and PR #41 boundary

**Source inspection:** PR #40 head 79f86f3; separate [draft collector PR #41](https://github.com/mikeokeeffe-droid/crypto-yall/pull/41) head 05e2959. Four PR #40 checks and two PR #41 offline checks were green during this review. These are **not** production or exchange-origin acceptance tests.

### Reviewed dependency and current state

| Original dependency | Offline-only work | Outstanding acceptance |
| --- | --- | --- |
| Account and market reads: user_state, spot_user_state, all_mids, meta | Five original read helpers and source-based sizing run against synthetic signer-free Info; PR #41 prepares five pinned testnet query types | Trusted independent read-only HTTPS collector, operator-pinned effective account/DEX, authenticated fresh distribution to ephemeral bot runners |
| Order status and CLOID-to-OID correlation | PR #40 has request planning and fixture lineage checks | Independently captured scoped orderStatus query and original durable journal matching |
| Partial fill and trade history | PR #40 has synthetic userFillsByTime coverage; original get_order_fill_totals falls back to None if history unavailable | Real continuous account-wide fills, incl. manual/other-bot activity, same-millisecond ties, API caps and retention; missing evidence means HOLD |
| Funding history | Original get_position_funding can return zero-valued funding with funding_data_complete=False | Verified funding-history API schema, time-window completeness and origin; a zero fallback is not authentic zero |
| Current net exposure | Synthetic conservation and paginated fixtures remain unverified | Fresh independently obtained position/open-order evidence, durable pre-submit baseline, full same-coin reconciliation |
| Network and process boundary | PR #41 disabled collector source, dedicated offline oneshot host probe and negative socket checks | Independent proof of effective secret/path/egress restrictions, collector-origin transport and audit evidence; separate approval for any one-shot testnet read |

**Important scope correction:** PR #41's read-only prototype supports clearinghouseState, openOrders, spotClearinghouseState, allMids and meta only. Its network entrypoint AND internal HTTPS transport helper deny real calls. It does not yet collect orderStatus, fills-by-time or funding history. A passing offline host probe is not a functioning authenticated exchange history service. The local Unix-socket CI service cannot be assumed reachable by remote ephemeral GitHub Actions bot workers.

### Next separately reviewable stages

1. Independently sign off the actual disposable collector host: code SHA, systemd identity, credentials and private-file ACLs, external egress, TLS verification, fixed endpoint and path, audit integrity and stop/rollback. The observed socket-creation denial tests narrow mechanisms only; they do not establish the entire boundary.
2. Design a **new separately reviewed, still network-disabled collector change** for orderStatus, fill-by-time and funding history, with current official Hyperliquid schemas and rate/retention limits verified. Require independently pinned effective account, DEX, clock, query bounds, replay protection, unique fills, immutable audit and explicit HOLD on gaps or saturated windows.
3. Only after independent review, request the operator's **explicit approval** for a named PUBLIC TESTNET account, exact one-shot read-only request types, limits and audit retention. Neither PR currently authorizes testnet or mainnet HTTP.
4. Bind independently captured read-only evidence to an immutable coordinator journal, review current account net position plus all unowned/manual fills, and prove coverage of the pre-submit baseline. The coordinator must not trust metadata supplied by bots or fixture manifests to claim authentication or completeness.
5. Separately implement and review the exclusive trading sender, bounded reduce-only close policy, uncertain-send recovery, emergency protective position management, and coordinated cutover of all three bots; independent risk/security sign-off required.

### Non-negotiable HOLD conditions

- No pre-submit baseline, lost history, ambiguous CLOID/OID attribution, partial fill windows, unknown/manual intervening order, unproved master/sub-account selection, stale snapshot delivery, missing origin proof or uncertainty after a sender crash.
- Incomplete original history, synthetic matching digests, caller-claimed completeness, zero-valued fallback funding, and passing Linux socket checks **cannot** become permission to send, close, claim ownership, release a lock or retry an uncertain order.
- Original Daily, Intraday and Aggressive still depend on signer-backed get_client(). A partial deployment or silent removal of current protective exit coverage is unsafe.

**HOLD DECISION: PR #40 stays DRAFT / LIVE NO-GO. PR #41 stays DRAFT / NETWORK DISABLED.** This update grants no merge, testnet request, real server change, secret access, production database permission, or trade.
