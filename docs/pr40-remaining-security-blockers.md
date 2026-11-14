# PR #40 — remaining blockers and next implementation gates

**Review status: DRAFT / LIVE NO-GO.** Offline test fixtures and documents do not change or protect the original live Daily, Intraday and Aggressive executors.

## Blockers, in priority order

| Priority | Gap | Required evidence |
| --- | --- | --- |
| P0 | Direct database/journal bypass | A separately deployed coordinator with exclusive journal write access; test that each bot's real runtime identity cannot access the database or journal file |
| P0 | Direct exchange-order bypass | Remove direct trading credential access from bot workloads and demonstrate that only the coordinator can sign/submit orders |
| P0 | Real workload identity | Authenticated service transport, independently verified bot-to-account/environment mapping, expiry/revocation, replay protection and audit |
| P0 | Exchange-side position provenance | Reconcile complete independent order/fill history and current net exposure, including manual and other-bot activity; hold on uncertainty |
| P0 | Safe close protocol | Explicit bounded reduce-only quantity, single-writer serialization, durable intent/fencing, idempotency and ambiguous-ack recovery |
| P1 | Service recovery and operational controls | Process crashes, journal loss/corruption, reconciliation outages, alerting, emergency stop and tested rollback |
| P1 | Non-production integration verification | Test real process/DB permission boundaries and failure injection without any production exchange orders |
| P1 | Independent sign-off | Security and trading-risk review plus explicit approval before any deployment |

## What has actually been tested — update 14 November 2026

- The independent group-gated socket fixture uses three actual Linux UIDs
  and a temporary supplemental socket group to compete for one synthetic
  account/DEX/coin scope. Exactly one reservation succeeds; disallowed UIDs,
  bot impersonation, and direct reads of the coordinator-private SQLite
  journal fail. This was verified through GitHub's completed offline CI
  workflow at commit `3d30fc62ae4f43ffef2ccc5b67eeade40182ef31`.
- Separate disposable PostgreSQL roles, process-bound admission, synthetic
  sender/journal/fill checks, stale-fence tests, and signer-free Info/entry
  interface fixtures also pass CI. These do **not** make the three original
  executors signer-free or establish real exchange order provenance.
- The group-gated test constructs a temporary socket and invokes the
  offline journal handler. It is **not** the original PostgreSQL process
  listener deployed under three real bot service identities. In fact,
  `offline_original_bot_process_listener_ci.py` deliberately creates a
  **0600** socket under a coordinator-private directory, and
  `offline_original_bot_entry_socket_client_ci.py` requires **0700**
  parent + **0600** socket ownership by the coordinator UID. That
  combination is same-UID-only and cannot serve independently identified
  bot UIDs. This mismatch remains a real implementation blocker.
- The original `get_client()` still reads `HL_PRIVATE_KEY` and
  instantiates a signer-backed Exchange in all three bots through imports.
  A passing AST characterization test explicitly records this as
  **unresolved**, not a secure state.

## Next implementation milestone (not yet complete)

**Bridge the group/OS identity boundary into the real *disposable* coordinator
listener and signer-free client pair** with one consistent reviewed IPC
permission contract: three individually pinned bot UIDs may reach only
the entry-request socket; unauthorized UIDs and spoofing remain HOLD;
all bot UIDs lack direct journal / DB writer credentials; exactly one
reservation persists on crash/restart. Preserve fail-closed syntax,
framing, nonce, schema validation and process-level tests.

Do not assume group membership alone proves identity: the server must
validate Linux peer credentials on each accepted connection and bind each
UID to a fixed bot/account/environment, with independent restrictions
on how workloads obtain membership. No real signing or exchange endpoint
may exist in this disposable integration.

After this, the larger unresolved work is a separately privileged
single writer, real workload secret isolation, exchange-backed
reconciliation, bounded reduce-only close, operational recovery, and
independent security/trading-risk approval. These cannot be satisfied by
more synthetic snapshots alone.

## Critical interpretation

Green CI for a disposable permission boundary does **not** mean a deployed
secure sender exists. The group-gated fixture runs with temporary identities
and storage; it does not prove service-level credential revocation,
production PostgreSQL permissions, egress restrictions or safe real orders.

**Keep PR #40 DRAFT / LIVE NO-GO.** Do not merge, deploy, change production
secrets, modify original live bots, access real Hyperliquid APIs or place
orders without a separate explicit approval.
