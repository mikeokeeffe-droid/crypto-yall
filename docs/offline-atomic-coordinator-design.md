# Offline atomic replay + claim design (NOT deployable)

## Problem and boundary

The current `offline_socket_journal_bridge_fixture.py` consumes a nonce in
`offline_persistent_replay_ledger.py` and subsequently reserves a scope in
`offline_sender_restart_journal.py`. These are separate SQLite databases:
the two writes cannot be committed together. A crash between them burns the
nonce without a claim. That is a safe HOLD but is not an atomic protocol.

This proposal is **offline-only**. Do not wire it to Daily, Intraday, Aggressive,
a signer, an exchange SDK, production state, or any order/close path.

## Proposed durable schema: one coordinator-owned SQLite database

- `replay_nonces(principal TEXT NOT NULL, nonce TEXT NOT NULL,
   PRIMARY KEY(principal,nonce))`
- `claims(environment TEXT NOT NULL, account TEXT NOT NULL, dex TEXT NOT NULL,
   coin TEXT NOT NULL, bot TEXT NOT NULL, token TEXT NOT NULL UNIQUE,
   cloid TEXT NOT NULL UNIQUE, fence INTEGER NOT NULL UNIQUE,
   state TEXT NOT NULL CHECK(state IN ('reserved','dispatch_unknown')),
   PRIMARY KEY(environment,account,dex,coin))`
- `metadata(schema_version INTEGER NOT NULL)` with strict version validation.
- A durable, monotonic fence counter must be allocated in the **same transaction**,
  not inferred from a potentially deleted claim.

## Single-transaction request

1. Validate peer UID, bot/account/scope, frame length and nonce **before** writes.
2. Open only the pre-provisioned coordinator-owned private database; validate
   owner, file type, directory and schema; fail closed on missing/corrupt state.
3. `BEGIN IMMEDIATE` on **one** SQLite connection.
4. Insert `(principal,nonce)` into `replay_nonces`. Conflict: `ROLLBACK`, HOLD.
5. Allocate a unique monotonic fence and insert the scope claim. Conflict:
   `ROLLBACK`, HOLD (the nonce is not burned for a rejected scope).
6. `COMMIT` before replying `reserved_offline_only`. On any database error:
   `ROLLBACK`, HOLD. Never return a reservation before durable commit.
7. If a response is lost, retrying the same nonce must HOLD. A different nonce
   for an already claimed scope must also HOLD. No live dispatch is authorized.

## Mandatory offline failure-injection tests

- Crash/exception after nonce insert but before claim: both changes roll back.
- Crash/exception after claim insert but before commit: both changes roll back.
- Duplicate nonce, concurrent same-scope requests, and concurrent distinct scopes.
- Commit succeeds but reply is lost: retry HOLDS across process restart.
- Database missing, read-only, malformed, wrong owner, symlink or replaced path:
  fail closed; no new database is created.
- Restart with `dispatch_unknown` must HOLD pending independent reconciliation.
- Explicitly verify **zero** SDK, signer, order, cancel, or close calls.

## Still blocked after atomicity

SQLite atomicity does **not** establish external exchange execution outcome.
Before any live use, require a managed coordinator process and UID/ACL policy,
authenticated bounded IPC, independent Hyperliquid order/fill/position
reconciliation, safe reduce-only close semantics, staged failure testing,
operational review and explicit separate live approval.

Do not merge or deploy this draft PR as a live trading system.
