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

## Verified offline milestone — 14 November 2026

- GitHub Actions on commit `61dc7aaf65881be0ab6de654c8fa566936f6d166` completed successfully: original bot order boundaries, Code Safety Check, disposable PostgreSQL and Supabase State Adapter tests. The group-gated real coordinator/listener step ran successfully in the PostgreSQL workflow.
- The **disposable** `offline_original_bot_process_listener_ci.py` and `offline_original_bot_entry_socket_client_ci.py` now have an explicit opt-in, root-only CI socket-group mode. Three **distinct Linux UIDs** connect to the actual one-shot listener under a temporary 0710 coordinator-owned directory / 0660 socket. The server uses kernel `SO_PEERCRED` to bind each UID to its fixed bot, account and environment, while a restricted PostgreSQL login is used only by the coordinator.
- CI demonstrates one winner and two HOLDs for the same synthetic account/coin, rejection of an unauthorized UID **with or without** access to the socket group, and preservation of the existing pending SQL reservation after the listener exits and restarts. The response never authorizes a trade.
- Earlier disposable SQLite file access checks also demonstrate denial of direct journal reads under another UID. They are **separate** fixtures: the PostgreSQL listener test is not proof of deployed SQL credential isolation.
- Synthetic Info and request-only adapters work without exchange signing; the existing three production executor modules **still import a signer-backed `get_client()`** and retain their trading mutation call sites.

## Next implementation gate — not complete

**Replace signing-capable bot initialization and direct order dispatch with a reviewed signer-free client and a separately privileged, single account-scoped writer.** Keep all three strategy calculations unchanged; cover entries, Aggressive pyramid adds, leverage updates, and every close path including unsized fallbacks. The sender must persist immutable intent, CLOID, fence and dispatch-unknown state before any possible order side effect. It must fail closed when journal, authentication or independent reconciliation fails.

Required evidence is **deployment-level**, not another green synthetic fixture: (1) bot workloads have no access to `HL_PRIVATE_KEY` or usable order-signing endpoint; (2) individually authenticated bot identities cannot access the sender's protected journal or SQL write roles; (3) signed mutations have exactly one independently audited dispatch choke point; (4) independent Hyperliquid order/fill/current-position evidence establishes ownership or preserves HOLD; (5) bounded reduce-only protective close and emergency STOP behavior are independently reviewed and tested; (6) a coordinated all-three migration and rollback are approved.

Do not assume socket-group membership itself is bot authentication, or that a pass on disposable, root-run Linux CI proves the server's real operational isolation, secrets, egress, account provenance or production-readiness. No production signer, testnet integration, rollout or real trading permission is created by these tests.

## Critical interpretation

**PR #40 stays DRAFT / LIVE NO-GO.** Do not merge, deploy, change trading secrets, alter the original executors or live workflows, connect real Hyperliquid trade endpoints or place orders without a later explicit review and authorization.
