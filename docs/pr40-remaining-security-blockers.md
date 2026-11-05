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

## What has actually been tested

- Disposable SQLite claims, simulated restart and pre-dispatch uncertainty.
- Credential-free identity fixtures and a narrow in-process coordinator request API.
- Simulated competing entry requests, duplicate/replayed requests and cross-account/environment rejection.
- A review-only synthetic ownership evaluator; close/dispatch endpoints remain disabled.
- Tests demonstrating that direct journal access bypasses the Python-level wrapper.

## Critical interpretation

A green CI result means the **offline checks passed**, not that a production-safe trading coordinator exists. Some negative close tests pass because the fixture unconditionally rejects every close request. Synthetic exchange evidence is not independent verification of actual Hyperliquid fills or positions.

## Recommended next safe implementation

Build a **separate local-process coordinator prototype with an isolated temporary SQLite directory and IPC**, without any exchange SDK, signer, network or production credentials. Exercise client inability to directly open the coordinator-owned database under distinct OS identities, then test authenticated transport separately. Do not represent Python object encapsulation or a same-user process as an OS security boundary.

Keep PR #40 draft and original live bots untouched. No live deployment until all P0 gates are closed and independently verified.
