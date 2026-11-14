# PR #40 — Read-only collector security gate and implementation handoff

**Review date: 2026-11-11 · DRAFT · LIVE NO-GO.** This is a security-gate decision for the *existing* Daily, Intraday and Aggressive bots. It grants no approval for a network connection, live trading, production DB migration, credential change, PR merge, or deployment.

## Findings from current branch

- Latest reviewed baseline `a30e208`: four CI workflows green. The tests use disposable PostgreSQL and synthetic exchange data.
- `offline_ci_info_capture_integrity.py` binds a synthetic SHA-256 digest, time, account, token, fence, CLOID and request type to supplied bytes. **A matching digest proves only integrity relative to a caller-supplied manifest; it cannot authenticate a Hyperliquid origin or establish complete history.**
- Existing `offline_hyperliquid_fill_window_audit.py`, `offline_hyperliquid_retention_gate.py`, `offline_hyperliquid_transport_plan.py`, and `offline_hyperliquid_capture_provenance.py` implement useful fail-closed **offline policy**, not a deployed network collector.
- The isolated `ci_sender_reviewer` has disposable read-only SQL access. It is **not** an authenticated live-exchange collector. An attempted additional SQL capture-role change was blocked; **do not retry or work around that change under this review**.
- Original bots retain direct exchange order methods; a real single-writer sender, authenticated reconciler, and vetted safe-close protocol do not yet exist. Passing CI does not address these P0 gaps.

## Confirmed external protocol constraints

Official Hyperliquid documentation describes `POST /info` reads, including `orderStatus` and `userFillsByTime`. The latter has **at most 2,000 fills per response**, only the **10,000 most recent fills** available, and **inclusive** `startTime` / `endTime` boundaries. Requests have weighted IP rate limits; `orderStatus` is weight 2, other read calls may be weighted higher and fill reads carry additional cost per returned item. Consult the current docs again before any implementation.

Sources:
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals

**Important:** Synthetic `next_cursor` fixtures in this PR are *not* an implemented Hyperliquid paging protocol. A public account query does **not** authenticate control of that account.

## Required security proof before proposing real read-only access

| Gate | Required evidence | Current decision |
| --- | --- | --- |
| C1. Operator-pinned scope | Approved master/sub-account, environment, perp DEX, exact official host, account-address verification independent of bot payload and agent signer | NOT VERIFIED |
| C2. Collector isolation | Standalone OS identity with no trading signer, exchange write path, live bot import, order authority, production DB mutation, or broad credentials; permissions verified as the effective process | NOT VERIFIED |
| C3. Controlled transport | HTTPS cert verification, exact host and `/info`, DNS/redirect/proxy/SSRF protections, fixed read-only request allowlist, bounded time/response size/rate budget, deterministic stop and logging | NOT IMPLEMENTED |
| C4. Genuine request provenance | Capture actual canonical request, pinned account, endpoint, OID/CLOID, time window, TLS/HTTP metadata, local clock and response hash *outside* server response; immutable audit access control | NOT IMPLEMENTED |
| C5. Account-wide coverage | Independently read order, unique fill IDs and all same-coin orders, including manual activity, open orders and live position; require durable pre-submit baseline | NOT VERIFIED |
| C6. Bounded history | Correct inclusive time windows and same-ms ties, no skipped or duplicated `tid`, fail closed on 2,000 response saturation, retention 10,000, gaps or rate limits; use independent archive for older evidence | NOT VERIFIED |
| C7. No automatic authority | Unknown, partial, failed, missing, stale or conflicting evidence => HOLD; collector cannot release claim, assign ownership, approve closes, or cause retries | OFFLINE POLICY ONLY |
| C8. Independently reviewed non-production check | Code and permission review, fixture/fault tests, explicit operator permission before a read-only testnet network request; audited rollback and incident response | NOT APPROVED |

## Minimal staged implementation

1. **Freeze additional overlapping fixture work in PR #40.** The branch is already very large. Consolidate the existing scope, parsing, window and retention guards into a single reviewed collector contract; remove contradictory assumptions before adding another new data model.
2. **Separate small reviewable collector change:** implement a dependency-injected, *network-disabled-by-default* read-only transport interface with strict configuration, a fixed request builder and a capture-envelope audit output. Unit tests must prove that invalid scopes, redirects, proxy overrides, wrong account, malformed payload, timeouts, 429 and capped windows produce HOLD. No database privilege changes.
3. **Security review before network:** verify isolated runtime identity and permissions, end-to-end provenance, effective egress restrictions, actual Hyperliquid schema mapping, rate weights and no signing or `/exchange` imports. Do not confuse SDK import bans with proven OS egress restrictions.
4. **Explicit approval needed for testnet-only reads.** Even read-only calls are not part of PR #40's current authorization. Select a designated testnet account after scope review and prove actual request-to-response binding; never use the current live bots or production account by default.
5. **Reconciliation remains HOLD** until complete independent evidence, a separately approved fenced handoff, and the single serialized sender + bounded reduce-only close paths exist. Treat legacy positions as unattributed until explicit operator investigation.

## Stop conditions

A single missing historical interval, uncertain API retention, same-ms fill tie, unexpected order, ambiguous response, missing pre-submit baseline, identity mismatch, unexpected network destination, loss of audit integrity, or a failed CI check is **NO-GO** for releasing a lock, retrying a trade, attributing position ownership, or closing a position automatically.

**Decision:** PR #40 stays **draft/unmerged**; original executors, live Actions workflows, Hyperliquid keys, production database and permissions remain unchanged. The next step should be a focused independent collector review—not further synthetic check-count inflation.


## 11 November 2026 — Read-only collector network cutover design checkpoint

**Reviewed PR head:** \`1398408\` (all four CI checks green before this documentation change). This section supersedes earlier phrases implying that green synthetic CI or a local Unix socket is actual exchange transport authorization. **Live NO-GO; testnet network calls not approved or made.**

### Verified pieces and exact gap

- \`offline_testnet_info_snapshot_plan_ci.py\` prepares only five canonical **testnet** \`POST /info\` body types: \`clearinghouseState\`, \`openOrders\`, \`allMids\`, \`meta\`, \`spotClearinghouseState\`. It cannot send a request.
- \`offline_readonly_collector_contract.py\` prepares only pinned \`orderStatus\` and bounded \`userFillsByTime\` capture plans; existing synthetic capture digests are **not** TLS/exchange origin authentication or history completeness.
- \`offline_documented_info_projection_ci.py\` projects documented-shape fake account responses into the signer-free helper snapshot. It discards extra fields; it does not authenticate inputs. \`offline_signer_free_info_service_ci.py\` serves one synthetic snapshot by a **same-host Unix socket**, not a network collector.
- The three original executors still call the trading-signing \`get_client()\`; direct \`market_open\`, \`update_leverage\`, \`market_close\` remain live-code paths, unchanged.
- **Architecture correction:** the bots run as GitHub Actions workers, typically in *separate ephemeral runner environments*. A Unix domain socket on a dedicated host is **not** remotely reachable from those jobs. A future remote data handoff must therefore be separately designed and authenticated; do not mistake the passing local socket tests for a deployable architecture.

### Minimal proposed production topology (future, not built)

1. One **independent collector process/service** on an isolated host holds a pinned, operator-approved **testnet** *effective account address* and performs only read-only \`POST\` calls to the exact \`https://api.hyperliquid-testnet.xyz/info\`. It never receives API-agent signing keys, exchange order capability, or database write privileges for trading state.
2. The collector emits independently generated capture evidence: canonical request bytes/hash, expected pinned account/type/time range, actual transport origin/TLS observations, HTTP status, response bytes/hash, collector clock, bounded retry/rate evidence, and append-only sequence identity. A self-declared "origin=hyperliquid" JSON field is never sufficient. A read-only account address is a lookup key, **not proof the operator owns it**.
3. A future isolated **read-only snapshot distribution** channel serves minimal validated market/account data to ephemeral GitHub Actions bot jobs. Delivery requires an independently authenticated service identity and freshness/replay checks; data must carry **no authorization** to submit, close, adopt, release or retry orders. Options (not approved) include narrowly scoped authenticated HTTPS read or a separately ACL-protected append-only store. A direct Unix socket is appropriate only between **co-located** processes.
4. The independent reconciler reviews evidence against account-wide open orders, actual OID/CLOID history, unique fill IDs, position netting and the durable pre-submit baseline; truncated or partial responses stay HOLD. Position ownership and close authorization remain separate, later projects.

### Network and runtime controls required before the first real read

| Control | Release evidence needed |
| --- | --- |
| Scope pin | Operator explicitly selects a separate **testnet** master/sub-account, exact default perp DEX and exchange host; never infer a live account from \`HL_ACCOUNT_ADDRESS\` or an API agent wallet |
| Read-only host | TLS certificate and hostname verification with pinned exact hostname and \`/info\` path; disable proxy inheritance, cross-origin redirects, arbitrary URL/host/headers, and automatic non-idempotent HTTP retries |
| Egress | Independently audited OS/container/cloud egress rule allows only the required HTTPS origin/destination; no \`/exchange\` path reachable through **application policy**; recognize that destination egress rules alone cannot enforce HTTP paths at an encrypted destination |
| No trade authority | Collector lacks any \`HL_PRIVATE_KEY\`, API signing material, exchange SDK trading client or credentials for writing production trading state; distinct runtime principal and read-only ACLs are audited as the effective process, not only in Python tests |
| Fixed request budgets | Explicitly allowlisted \`type\` and fields, fixed account, serialized bounded request rates, timeouts, max body sizes, 429/5xx => HOLD and no implicit "zero orders" conclusion |
| Account history | A response containing 2,000 fills is **saturated**; Hyperliquid exposes only the most recent 10,000 fills for this query. Inclusive bounds and same-millisecond ties require deduplication, window continuity and durable archive or HOLD |
| Authenticity and freshness | Audit metadata gathered by the trusted collector from the actual transport; independently authenticated remote data handoff to bots; reject stale, altered, gapped or replayed captures |
| Operations | Peer review, fail-closed stop/rollback, no mutation of original bots, explicit subsequent approval before a **single** designated testnet account read; production approval separately required |

**Rate budget reminder:** Official rate limits specify a shared IP-weight budget (currently documented as 1,200/min); \`allMids\`, \`clearinghouseState\`, \`orderStatus\` and \`spotClearinghouseState\` have weight 2, while many other \`info\` requests have weight 20 and fill calls add returned-item weights. Re-check before network activation; do not poll on the assumption that all reads are free.

**Documentation verified:** 
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/spot
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits

### Hard decision and next approval boundary

**Review decision:** the next code review should be a **small separate, security-reviewed collector transport implementation**, not more synthetic ownership fixtures in the 500+-commit draft PR. Do **not** enable real HTTP by changing a fixture flag, wire a real account into fake capture assertions, import \`hyperliquid.exchange\`, grant capture SQL permissions via a workaround, or merge PR #40 as a shortcut. Real testnet reads require a designated testnet account and operator authorization after the transport and runtime controls are reviewed. No mainnet reads, no signed API, no orders, no production deployment are included in this step.


## Read-only network implementation audit — 11 Nov 2026 (PR head eab34b1)

**Review outcome: STOP / NO TESTNET REQUEST YET.** All four offline CI workflows passed on \`eab34b1\`; they are **not** evidence of a completed HTTPS collector. The original Daily, Intraday, and Aggressive executors remain unchanged. This audit does not approve a real Hyperliquid call, testnet activity, secret access, new database permissions, PR merge, or a live deployment.

### What source code actually does

| File | Verified present functionality | Not implemented |
| --- | --- | --- |
| \`offline_testnet_info_snapshot_plan_ci.py\` | Pure plans for five pinned testnet-only \`/info\` query bodies; fixed rate-weight preflight; checks **caller-supplied** fake response envelopes | HTTP connection, actual TLS verification, DNS/proxy/redirect enforcement, authenticated capture log |
| \`offline_readonly_collector_contract.py\` | Pure \`orderStatus\` and bounded \`userFillsByTime\` request/capture review; untrusted fixture hashing | Actual exchange-origin proof, complete history, independently verified OID/CLOID/position ownership |
| \`offline_testnet_https_transport_candidate_ci.py\` | An **inert public stub** that always returns HOLD; intentionally has *no* HTTP, SSL, socket or request implementation | The first real read-only HTTPS request; cannot be activated by a flag or CI setting |
| \`offline_signer_free_info_service_ci.py\` | Same-host Unix socket carrying a synthetic, unsigned snapshot under CI test identity | Authenticated remote delivery from a collector host to ephemeral GitHub Actions bot runners |
| \`tests/test_offline_collector_network_import_guard_ci.py\` | Source-level check for risky imports/calls in seven **offline** modules | OS/container egress restriction, runtime permissions, complete dependency audit |

**Key correction:** do not describe the existing stub as a working or already-built HTTPS transport. It is only a disabled interface. Additional synthetic CI cases alone cannot satisfy gate C3/C4.

### Required small *separate* reviewed implementation to unblock step 1

1. **Designated testnet effective account:** Obtain an operator-approved **public** testnet master/sub-account address. Do not reuse mainnet \`HL_ACCOUNT_ADDRESS\` or an API-agent signer address by default. A public address alone is a lookup identifier, not account-ownership proof.
2. **Collector runtime and networking:** Isolate a dedicated service with no \`HL_PRIVATE_KEY\`, \`hyperliquid.exchange\`, direct order endpoints, production DB write credentials or bot execution access. Verify actual effective UID/container permissions and egress at runtime. HTTPS to a fixed official *testnet* hostname, port 443, \`POST /info\` only, no redirects, proxy inheritance or arbitrary URL/headers.
3. **Operational request bounds:** Enforce TLS certificate/hostname checks; a pinned canonical body/type/account; 4s timeout and 256 KiB cap; strict JSON/content encoding validation; fixed rate budget and no blind retries. HTTP 429, 5xx, TLS mismatch, unexpected address, partial content, response truncation and ambiguous result => HOLD. A network permit must not be an environment variable or caller boolean alone.
4. **Source-backed capture:** Record the **actual** request and response bytes/hashes, endpoint, exchange account, HTTP/TLS observations, observed clock, request sequence, failure state and durable audit trail from inside the independently authenticated collector. A matching digest of untrusted fixture bytes does not prove exchange origin. Ensure external reviewers can validate capture provenance without giving bots order rights.
5. **Snapshot distribution across runners:** A hosted collector's Unix socket cannot be reached by a remote GitHub-hosted Actions worker. Design a separately authenticated, least-privilege read-only HTTPS endpoint or ACL-controlled snapshot store with anti-replay, scope pinning and freshness. Bot jobs must not receive exchange signing or production database write permissions.
6. **No ownership upgrade:** \`openOrders\`, \`clearinghouseState\` and \`userFillsByTime\` must be joined with a durable independently observed pre-send baseline, bounded inclusive pagination, same-ms duplicate handling, other manual/agent activity and account-wide position changes. Unattributed or incomplete histories => HOLD, with no auto-close, claim-release, retry or position adoption.
7. **Review and one-shot permission gate:** Put real network implementation in a **small separately reviewable change**; test it first with a deliberately nonnetwork fake transport and explicit OS-level egress-denial checks. Before the first actual \`POST /info\` request, obtain separate user approval for the exact public testnet account, intended request type, scope and collector host. Document rollback and audit handling. No live exchange or trading permission is implied.

**Acceptance evidence for step 1:** A separately approved testnet-only \`/info\` request performed by an isolated read-only process with independently verified TLS/HTTP provenance, a timestamped bounded response and demonstrated lack of any trading capability. This proves only that the read-only collector works; it does **not** authorize the central order sender, reconcile all history, or permit live trading.

**Next engineering action:** Stop expanding PR #40's overlapping offline test fixtures. Review the dedicated collector runtime/transport design separately, then request a public testnet account and explicit permission *before* any network read. The original bots, live workflows, credentials, and production account stay untouched. **LIVE NO-GO.**
