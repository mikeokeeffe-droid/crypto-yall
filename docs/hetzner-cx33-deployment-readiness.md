# Hetzner CX33 deployment readiness — planning only

**Status: DESIGN ONLY — NOT DEPLOYED.** Target: one Linux VPS for Daily, Intraday, and Aggressive Hyperliquid bots after independent safety approval. No server purchase, DNS, secrets, database migration, workflow changes or live execution is authorized by this plan.

## Safety-first cutover sequence

1. Before any production migration, confirm the latest draft PR #38 tests pass, review its execution boundaries and fencing/ambiguous-fill behavior, and obtain an independent review. Passing CI alone is insufficient.
2. Provision a dedicated Hetzner VPS in the selected EU region only after explicit user approval of the final quoted price and recurring extras.
3. Secure Linux: non-root operator, SSH keys only, firewall default-deny inbound, automatic security updates, audit logs, restricted outbound access, and tested recovery access.
4. Run bots under separate restricted service users and systemd services. Never embed trading keys in scripts, repository files, command lines, images or logs. Keep credentials in restricted files or a secrets manager with rotation and revocation procedures.
5. Use one local PostgreSQL instance with distinct per-bot access identities and least-privilege permissions. Keep exchange reconciliation and ownership recovery separate from order submission.
6. Start on **read-only / order-blocked** simulation, with fake exchange transport. Test that server restarts, database outages, simultaneous entries, stale reservations, and uncertain/partial fills cannot create duplicates.
7. Add health monitoring and alerting: bot heartbeat, database connectivity, reconciliation backlog, unreconciled orders, service restarts, exchange connectivity and disk space.
8. Test encrypted off-server backups and restore, firewall checks, kill switch, and full stop/rollback.
9. Ensure **only one execution authority**: before any production cutover, disable and confirm all overlapping GitHub scheduled order-executing workflows, then activate VPS execution under explicit approval. Never run GitHub and VPS live order executors concurrently.
10. Gradual controlled rollout, with documented stop conditions and manual approval for any real-money order placement.

## Expected operational model

- Daily bot: independent scheduler respecting strategy clock and market data.
- Intraday bot: independently scheduled with risk checks before each entry.
- Aggressive bot: separate schedule and shared durable reservation lock.
- Reconciliation service: on independent schedule, no authority to initiate fresh market entries.
- PostgreSQL: persistent owner of entry reservations and durable order intent state; stale TTL by itself must never release an ambiguous fill.
- Observability: rotating logs, heartbeat and failure notifications.
- Fail-closed default: if exchange state, database, owner or order finality is unknown, no new entry.

## Go / No-Go

| Gate | Result |
| --- | --- |
| Draft PR #38 reviewed and accepted | PENDING |
| Isolated Postgres automated tests | PASS for commit d3981b503445c617ef6c946328acba034be56e9d; recheck after new commits |
| Independent security review of live order path | PENDING |
| Server purchase and hardening | NOT STARTED |
| Staging-only installation and restart tests | NOT STARTED |
| Encrypted backup and restore rehearsal | NOT STARTED |
| Single execution authority cutover rehearsal | NOT STARTED |
| User authorizes real-money cutover | NOT AUTHORIZED |

**Decision: NO-GO for production.** This guide creates no recurring costs.
