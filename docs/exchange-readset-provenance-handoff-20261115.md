# Exchange history handoff — offline provenance gate

**15 November 2026. DESIGN / SYNTHETIC FIXTURES ONLY.**

The proposed read-only adapter must obtain independent, authenticated,
account-wide evidence before a future sender can even consider a close.
`sender_review/exchange_readset_gate_offline.py` documents a synthetic
manifest gate. It does **not** fetch or authenticate any Hyperliquid data.

## Required read-set inputs

- Account positions **before** the other reads
- Account-wide orders, with explicit pagination and complete identifiers
- Account-wide fills, with explicit pagination and unique fill identifiers
- Outstanding open orders, including manually created orders
- Account positions **after** the other reads

The fixture gate checks one testnet account and read batch, a single
sequential pass, monotonic timestamps, capped page sizes, exact cursor
continuity, unique per-endpoint IDs and a terminal page. It compares
synthetic position digests before/after and rejects pending unknown-order
IDs. All inputs including completeness claims and digests are untrusted;
a matching result remains HOLD.

## Real-world requirements not implemented

Actual Hyperliquid endpoints may differ in pagination and time windows.
A production read-only collector must separately document and test the
provider's **actual** coverage, retention, signing/authentication, response
ordering, record identifiers and pagination semantics. Matching hashes
cannot by themselves prove no trade occurred between two observations.
An independently maintained account-wide sequence/checkpoint and a
durable database lock or equivalent exchange-validated mechanism must
bridge any race before execution.

Before any protective close, independently reconcile position sizes to
order/fill history, attribute legacy and manual trades, distinguish unknown
ACK and partial fill, validate fence and position ownership, and enforce
bounded exchange-native reduce-only sizes. Any ambiguous ownership,
missing page, stale snapshot, open order or outage must trigger
conservative operator escalation—not a blind order retry.

**No HTTP client, OIDC runtime authentication, real account records,
database writes, exchange signing or trading deployment exists here.
PR #42 remains draft. TESTNET / LIVE NO-GO.**
