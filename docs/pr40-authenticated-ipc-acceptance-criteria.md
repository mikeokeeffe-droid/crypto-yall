# PR #40 — Authenticated coordinator IPC acceptance criteria (offline only)

**Status: NO-GO for live deployment.** This is a design and negative-test
checklist, not proof of an implemented production security boundary.

## Trust and deployment boundary

- Each original bot runs as a distinct, unprivileged OS identity. The coordinator
  runs as a separate service identity, with exclusive journal/database credentials,
  exchange signing authority and server authentication material.
- Bots must not inherit the coordinator's file descriptors, secrets, environment,
  database connection strings, or ability to execute arbitrary coordinator code.
- Only a narrow authenticated request interface is exposed. Never accept caller-
  asserted bot names, account scopes, or environment as authentication evidence.
- For local Unix sockets on Linux, verify kernel peer credentials (SO_PEERCRED)
  on each accepted connection and map an allowed UID to exactly one bot/scope.
  A socket path alone, mode bits alone, or an HMAC supplied by a same-UID process
  does not prove a separate process identity. For remote transport, require
  mutual authentication and independent credential storage.
- Use strict socket ownership and directory permissions. Treat unknown UIDs,
  missing peer credentials, wrong scope, malformed messages, and unsupported
  operations as HOLD. No direct journal access from bot identities.

## Replay, restart, and authority

- The coordinator verifies requests before processing them and persists nonce/
  request-id consumption atomically in its own protected store. Deny replay
  across connections, worker restarts, and concurrent requests.
- Define a bounded message schema, size and timeout; handle malformed, partial,
  oversized and abruptly disconnected clients without unsafe side effects.
- A verified request may reserve an offline claim; it must never independently
  authorize order submission or position closure. Dispatch requires durable
  fencing, exchange order/fill reconciliation and explicit uncertainty handling.
- Closing requires independent, fresh evidence of bot-owned remaining size and
  an explicitly bounded reduce-only order. Unknown/manual/other-bot activity,
  stale evidence, restart ambiguity or incomplete fills must HOLD.

## Required offline tests before deployment consideration

1. Distinct-UID client can connect through the intended socket and is mapped to
   its kernel-authenticated bot identity, not its claimed name.
2. Unknown UID, bot spoofing, cross-account/environment, socket replacement and
   missing peer-credential scenarios all HOLD.
3. The bot UID cannot read coordinator key material, SQLite journal, replay
   ledger or signer credentials; same-UID bypass is explicitly demonstrated.
4. Concurrent and restarted requests cannot reuse a nonce or claim the same
   account/dex/coin scope twice.
5. Connection drop before/after a durable write, malformed payloads, and server
   crash/restart fail closed; no unjournaled dispatch or close is possible.
6. Independent exchange reconciliation and safe reduce-only close semantics are
   exercised against a paper/staging environment before any deployment review.

## Scope limitation

Current PR #40 fixtures use multiprocessing Pipe, synthetic identities, HMAC
test secrets, disposable SQLite and root-runner permission audits. These are
useful negative tests but **not authenticated production IPC**. No original
live strategy, production database, wallet, deployment or exchange order is
changed by this plan.
