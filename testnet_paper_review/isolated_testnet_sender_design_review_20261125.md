# Isolated Daily TESTNET sender — implementation boundary and remaining work

**Decision: NO-GO.** This is a design review, not authorization to send, sign, merge, deploy, run a new network service, or trade. No exchange keys, original bot workflows, Mainnet credentials, or production state may be reused.

## What is now proven in PR #46 (offline only)
- Fake-exchange test of the pinned original Daily trade function; no real Hyperliquid order.
- Fixed Testnet address and endpoint checked against synthetic fixtures.
- One-shot synthetic USD notional range $12–$25 and exactly 1x leverage; simulated writer/side/symbol checks.
- A disposable SQLite fixture with a persistent claim and one-way freeze, tested for competing claims, simulated restart, unknown acknowledgment, reconciliation and duplicate attempts.
- **Important recovery regression fixed:** opening the journal no longer silently creates a new database. An explicit initialize=True is required for a fresh, disposable test fixture. Missing file, malformed file, missing schema and deleted freeze-control row trigger HOLD rather than reinitialization.
- PR-only GitHub CI has no signing secrets and cannot submit exchange orders.

## Required production-capable isolation, not implemented
1. **Independent signer:** A separate strictly Testnet-only trading agent, restricted environment, exact account binding, appropriate permissions, expiry and security review. The existing read-only agent check is not an order-permission audit.
2. **Hard endpoint and host boundary:** Compile/configure a single Testnet-only URL; enforce Mainnet block at source, dependency, transport and egress layers. No runtime network override or fallback.
3. **Shared durable journal:** Choose independently reviewed host/storage design (not this disposable fixture). Require atomic one-writer lease, unique request and immutable order identifier, persist-before-sign/send, fsync/transaction durability, operator identity and tamper-evident audit log.
4. **No blind retry:** Treat every transport timeout, crash, partial fill, unknown order acknowledgment or state disagreement as HOLD; recover only with fresh, independently validated exchange account/order/fill reads.
5. **Real limits:** Block anything outside fixed operator-approved account, SOL symbol, side, one order, hard notional/leverage cap, expiry and unambiguous position limit. Enforce budgets across restarts and process boundaries, and verify exact exchange metadata/minimum/rounded size.
6. **Halt and exposure exit:** A real emergency stop must block signing and new sends even when process/DB unhealthy. A stopped sender does not imply the position is closed. Build reviewed, explicitly sized reduce-only close/cancel procedure with independent verified ownership, exchange state and separate operator approval.
7. **Operational separation:** Dedicated runtime identity, fresh credentials, least-privilege storage permissions, no shared Mainnet env vars, no active scheduler, no original Gist or production Supabase mutation, and independent review of hosting firewall/systemd/GitHub privilege controls.
8. **Verification:** Offline adversarial tests plus independent review, controlled signed no-order dry run, live read-only checks, approvals of exact code version/configuration and one intended Testnet trade. Leave sender disabled after the trial.

## Explicit non-goals
- No Testnet or Mainnet trade, no real cancel/close, no old workflow dispatch, no background schedule, no server changes.
- No claim that one-VM disposable SQLite proves distributed fencing, safe signer isolation, exchange recovery, real stop-loss behavior or deployable safety.
- No implicit green-light from green CI, previously confirmed API-wallet association, or use of an existing wallet.

**Next safely reviewable slice:** threat-model the signer, ownership journal and atomic reconciliation interfaces; then use mocks only for real-world failure cases (crash immediately before/after network submission, in-flight requests, partial fills, stop failure, DB corruption, restart).
