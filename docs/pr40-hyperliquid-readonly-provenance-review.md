# PR #40: Hyperliquid read-only evidence and account provenance review (NO-GO)

2026-11-03. Design review only; **no API calls, credentials, live orders,
production database access, migrations, deployment, or merge**.

## Core finding: synthetic "account" fields are not authentication

Existing `offline_exchange_page_review.py` and
`offline_paginated_exchange_evidence.py` deliberately accept **fake**
`account`, `snapshot_id`, `complete`, `next_cursor`, and timestamps.
They reject internal inconsistencies, which is useful, but **do not prove**
the records came from Hyperliquid or from the desired wallet. The completed
CI tests demonstrate offline policy behavior, not live exchange safety.

The real Hyperliquid `/info` API uses a `user` query argument to select
account data. A different caller can request another user's public data.
Response fields alone cannot authenticate the query's origin. An independently
deployed, reviewed, restricted read-only transport must bind every response to
the exact request and an operator-approved account address.

The docs explicitly warn: use the **master or sub-account address**, not the
agent/API wallet address, which can return empty results.

Official sources:
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api

## Read-only evidence sources (future work, not connected)

Use only `POST https://api.hyperliquid.xyz/info` on a separately reviewed
HTTPS transport, with an allowlist of **read-only** request types:

| Purpose | Official `type` | Caveat |
| --- | --- | --- |
| Exact exchange order by original OID/CLOID | `orderStatus` | Request binds `user` and `oid`; missing/unknown/rejected is not automatically final no-fill |
| Open orders | `frontendOpenOrders` or `openOrders` | Response may not echo `user`; bind to recorded original query; account-wide for the selected DEX |
| Filled trades | `userFillsByTime` | Explicit `user`, `startTime`, `endTime`; server cap of 2,000 per response; only 10,000 most recent fills available |
| Perpetual positions | `clearinghouseState` | Explicit `user` and DEX; a live position snapshot is not an atomic historical baseline |
| Optional role review | `userRole`, `subAccounts` | Check master/sub-account mapping only when needed, with official schema and request limits |

All raw responses require strict schema validation before mapping to the
synthetic policy format. For example, the official fill shape uses `oid`,
`tid`, `time`, `sz`, and `coin`; the draft offline policy expects
`order_id`, `fill_id`, `time_ms`, and `size`. Never silently invent or
default absent fields. Respect PERP vs SPOT and DEX namespace differences.

**Important:** The draft synthetic `next_cursor` contract is NOT the
published Hyperliquid fill pagination protocol. The docs describe inclusive
time-based history queries and timestamp-based pagination; some general
time-range API responses have a 500-element limit. Do not translate synthetic
cursor tests directly into a working API client.

## Required trusted transport boundary

1. Operator separately approves **one immutable 42-character account address**
   (master or intended sub-account), environment (mainnet/testnet), instrument
   class (perps), and exact DEX namespace. Store this in restricted,
   independently reviewed configuration. Do not accept the account from any
   bot order, model output, mutable database row, response JSON, or agent key.
2. Only a separate, least-privileged review process constructs `/info`
   requests. Record the canonical request type, exact selected account,
   original OID/CLOID, DEX, time bounds, endpoint, capture time, request ID,
   and response digest in internal audit metadata produced **outside** the
   exchange response. A response-provided `account` or `complete` flag must
   never be trusted as identity or history-completeness proof.
3. Independently validate HTTPS TLS/certificates and exact allowed API host.
   Disallow caller-supplied URLs, redirects to other hosts, insecure TLS,
   live exchange actions, signing, private keys, or write privileges.
   Public read-only `/info` queries **do not authenticate wallet ownership**;
   trust is in the controlled configured address and transport, not in a
   signed response from Hyperliquid.
4. Check every returned order OID/CLOID, coin, side, status, original requested
   size and submission timestamp against durable intent. Verify separately
   collected fills, open orders and position evidence for the same pinned
   account and DEX. Re-read the original order and durable intent to detect
   observable changes. Treat non-atomicity as a residual risk.
5. Treat every missing field, timeout, invalid JSON, HTTP error, wrong account,
   wrong order, rate limit, inconsistent snapshots, or uncertain status as
   **HOLD**, not proof of rejection or ownership.
6. For `userFillsByTime`, cover the full required window, including enough
   history preceding submission to rule out other same-coin activity. Handle
   *inclusive* millisecond boundaries and multiple fills sharing the same
   timestamp without skipping or double-counting them. If a saturated page,
   timestamp tie, API response cap, retention cap, or unavailable earlier
   history makes completeness unprovable, **HOLD**. Never infer "no fills" from
   an empty `userFills` (latest-only) response.
7. Never infer historical flatness from a fresh `clearinghouseState`: the
   pre-submit baseline must have been durably recorded before order dispatch,
   bound to bot, claim, fence token, order context, account and DEX. If absent,
   **HOLD**.
8. Even complete, correctly bound responses only permit an **offline manual
   review candidate**, not database release, live retry, or ownership handoff.
   Atomic fencing/CAS, ownership transfer, stale-worker prevention at exchange
   submission, audit and independent security approval remain missing.

## Concrete next offline tests before any client exists

- Raw **documented** `orderStatus` fixture: exact OID/CLOID match; reject
  unknown order, non-final status, malformed JSON, unexpected side, coin,
  size, time or account query.
- `userFillsByTime` fixtures: deterministic account and DEX request binding;
  `tid` uniqueness, same-millisecond ties, partial fills, page overlap,
  missing or saturated 2,000-item page, and 10,000-history retention limit.
- Position and open-order fixtures: fail on wrong DEX, wrong user query,
  unexpected competing orders, absent historic baseline, stale capture.
- Fault injection: timeout during second read, TLS or host mismatch,
  rate limiting, replayed cache data, changed order status across reads.
- Prove fake caller-supplied `account`, `fresh`, `complete`, `snapshot_id`
  cannot upgrade a HOLD decision to an authorized database operation.

CI must remain offline, without production secrets. Any future read-only
testnet/mainnet access requires separate operator approval and a documented
privacy, credential, rate-limit, and rollback review.

## Status

**NO-GO** for staging promotion or live deployment. Existing pagination
prototypes are useful structural defenses, **not** an implementation of
Hyperliquid's actual page protocol or proof of account origin. PR #40 remains
draft. No merge or live bot changes are authorized.
