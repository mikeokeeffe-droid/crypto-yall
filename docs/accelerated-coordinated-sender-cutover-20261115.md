# Accelerated coordinated three-bot cutover — sender implementation plan

**15 November 2026. 4–6 weeks is an aggressive target, not a guarantee.**
**DRAFT ONLY · LIVE NO-GO · NO TESTNET NETWORK, ORDERS OR DEPLOYMENT AUTHORISED.**

This is a **small separate review workstream based on main**, not an invitation to
merge PR #40 or #41. It exists to turn the original Daily, Intraday, Aggressive
bots into a single-writer architecture without changing their strategies or
making new unsafe order paths. No source in this PR imports a signer, calls
Hyperliquid, opens a socket or accesses the production database.

## Parallel delivery map

| Workstream | Immediate deliverable | Acceptance evidence |
| --- | --- | --- |
| 1. Stop redundant fixtures | Freeze overlapping mock-only tests in [PR #40](https://github.com/mikeokeeffe-droid/crypto-yall/pull/40); retain all existing green safety checks | Existing four workflows remain green and exact source/strategy behavior is preserved |
| 2A. Read-only evidence | Complete [PR #41](https://github.com/mikeokeeffe-droid/crypto-yall/pull/41) security and scoped history capture review, without enabling the collector | Independently reviewed effective host permissions, captured real testnet-origin request/response only after separate approval, no signing key |
| 2B. Single protected writer | Implement the sender in **this focused workstream** with fixed operator-bound identity/scope, durable attempts/fencing and no direct bot submit | Isolated service identity, DB ACL, network restriction, exactly-one-writer tests and audited exchange transport; no unknown-outcome retry |
| 3. All-three cutover | Replace signer-backed `get_client()` and direct mutations in three bot jobs in one coordinated change | Runtime secret-absence and egress proof for all workers; preserve Daily/Intraday/Aggressive sizing/signals/TP-SL; handles aggressive pyramid and leverage; authenticated remote job-to-host transport |
| 4. Independent review | Security reviewer **other than implementer** checks exact code, credentials/ACL, recovery, unowned legacy positions, protection on outage | Written approval referencing exact commit and host evidence; tests alone are insufficient |
| 5. Controlled testnet | With explicit operator approval, designated testnet effective account, read-only request budget then separate small testnet order/recovery drills | Recorded request/response provenance, order/fill ownership reconciliation, protective-close fail cases and operator go/no-go |

## Deployment architecture (proposed, not operational)

```text
GitHub Actions Daily ─┐
GitHub Actions Intraday ─┼─ authenticated remote request-only API ─┐
GitHub Actions Aggressive ┘                                       │
                (no HL_PRIVATE_KEY, no trading Exchange client)   │
                                                                  ▼
                                 coordinator / durable journal / risk gate
                                    (effective account + DEX + coin lock)
                                          │
                                 exchange evidence reconciler
                                    (independent read-only collector)
                                          │
                            only approved, exclusive, fenced sender
                            (sole trading signer, no blind retries)
                                          │
                                   Hyperliquid exchange
```

### Sender trust boundaries, to be implemented and independently reviewed

1. **Request identity:** workload identity established by a server-side verified
   credential bound to Daily, Intraday, Aggressive, with expiry and replay
   protection. A caller field such as `bot`, `account`, `environment`,
   `cloid`, `ownership_verified` or `submit_authorized` conveys **no authority**.
   GitHub Actions runs remotely: a Unix socket on a host alone cannot serve
   ephemeral GitHub runners.
2. **Fixed scope:** operator-reviewed effective master/sub-account, network, DEX,
   coin and maximum risk are resolved on the server, not taken from a request.
   Isolate testnet/mainnet credentials and databases.
3. **Order intent before sending:** validate strategy action and rounded exact
   decimal quantity; store immutable identity, order intent, quantity, requested
   leverage, unique CLOID, lock/fence and *fresh pre-send baseline* in a
   transaction before attempting a signed exchange send.
4. **Single writer:** no worker can import a functional `Exchange`, read
   `HL_PRIVATE_KEY`, update leverage or submit an order. No second sender,
   personal/manual bypass or competing bot can undermine exclusivity.
5. **Uncertain acknowledgement:** persisted `attempt_started` precedes send;
   timeouts, crashes, duplicates, missing OID, partial fills, stale fences,
   rate limits, invalid history or reconciliation disagreement move to
   **HOLD**, never a blind automatic retry or claim release.
6. **Close and emergency protection:** no unsized `market_close(coin)` or
   unverified same-side account position adoption. A protective close must
   be explicit-size, bounded, reduce-only, direction-correct, attributed to
   independent fills/baseline, serialised under the same account lock and
   independently reviewed. Failure to protect an existing position during
   cutover is a **release blocker**, not a harmless HOLD.
7. **Cutover policy:** no partial live migration. Drain/stop old writers,
   assess legacy positions and active orders, revoke old signing access,
   confirm no bot can submit, then enable only the separately approved sender
   under monitored controlled testnet. Rollback must not restore multiple
   writers while an attempted order outcome is unknown.

### First three implementable slices (order matters, parallel review allowed)

- **S1 — Read-only architecture and request/auth contract:** define strict
  versioned request schema, authenticated remote trust boundary, exact-scoped
  signer-free bot bootstrap and no-authority response. Negative tests for
  replay, caller identity spoofing and stale credentials. No network or signing.
- **S2 — Exclusive sender durable journal and recovery:** write account-scope
  transactional claim/fence/CLOID and attempt lifecycle behind disposable DB
  credentials. Review SQL roles/DDL independently; **do not circumvent blocked
  production DB permission changes from PR #40**. Record unknown ack as HOLD.
- **S3 — Signed sender + independently verified testnet evidence:** implement
  strictly separated signing transport only after S1/S2 review, collector
  provenance and operator-approved TESTNET request/account. Implement
  reduce-only protective closes only with verified fill attribution, bounded
  size, and explicit failure-mode operator sign-off.

## Critical-path risks and dates

- **Weeks 1–2 (15–29 Nov):** security review of collector + sender S1/S2 in
  parallel. These require engineers/reviewers and host evidence, not just CI.
- **Weeks 3–4 (30 Nov–13 Dec):** coordinated isolated integration + separately
  approved testnet reads/trades *if prerequisites pass*. Do not infer approval.
- **Weeks 5–6 (14–27 Dec):** outage/partial-fill/reversal/roll-back drills and
  independent security/risk go/no-go, with contingency into January 2027.
- **No-GO extension:** if runtime isolation, provenance, fill coverage, exclusive
  sender, safe TP/SL or reviewer approval is missing, move the target rather
  than lower a safety gate.

## Release checklist — all required

- [ ] PR #41 collector runtime and end-to-end origin reviewed, no signer
- [ ] Independent account-wide order/fill/position baseline verified
- [ ] All three bot workers proven signer-free and no direct order egress
- [ ] Single scoped sender, durable attempt and strict journal fences
- [ ] Leverage, Aggressive pyramids, entry, TP/SL, kill-switch all accounted for
- [ ] Safe explicit-size reduce-only close and emergency outage policy
- [ ] Unknown results HOLD without unbounded retry, and safe rollback
- [ ] Approved testnet read and later separately approved testnet trade tests
- [ ] Independent security and trading-risk sign-off on exact revision
- [ ] Separate explicit live deployment authorisation

**Current status:** planning/review workstream started; no sender implementation,
no new real API access or deployment. All steps are intentionally unapproved
until their specific evidence is available.
