# PR #40 — Exact three-bot signing and order-dispatch cutover inventory

**2026-11-11 · Draft-only implementation handoff · LIVE NO-GO.**
Reviewed branch \`7607df7\` by reading all three original executor source files. This is not a change to any bot, secret, live workflow, database, exchange account, position, or order. PR #40 stays unmerged. This inventory must be reconfirmed against the exact commit chosen for any later deployment.

## Why a single sender is still mandatory

The current **Daily, Intraday and Aggressive** entry decision functions preserve local strategy logic, but all three processes can obtain the trading signer. Their account-level \`foreign_coins\` check is a snapshot, not an atomic lock across GitHub Actions workers.

**Critical dependency discovered:** Daily's \`hyperliquid_executor.py:get_client()\` (lines 189–203) requires \`HL_PRIVATE_KEY\` and \`HL_ACCOUNT_ADDRESS\`, constructs \`Account.from_key\`, then constructs both \`Info\` and an authenticated \`Exchange\`. Intraday imports that function at line 34 and calls it at line 653; Aggressive imports it at line 35 and calls it at line 642. Daily itself calls it at line 1153. **Removing direct submission functions alone is insufficient while the three bot processes continue to load a signing-capable Exchange client.**

## Exact executable mutating call sites on reviewed branch

| Bot | \`market_open\` | \`update_leverage\` | \`market_close\` (explicit size / **unsized fallback**) | \`execute_trade\` |
|---|---:|---:|---:|---:|
| Daily — \`hyperliquid_executor.py\` | line 498 | 493 | 441 / **443** | 434 |
| Intraday — \`intraday_executor.py\` | line 555 | 550 | 490 / **492** | 476 |
| Aggressive — \`aggressive_executor.py\` | line 552 | 547 | 506 / **508** | 501 |

These are 12 direct SDK mutation *call expressions* across the original three modules (three opens, three leverage settings, six close alternatives). This is a scoped source inventory, **not** proof that other repository files, GitHub Actions, manual traders or independent API agents lack additional order paths.

The original Aggressive \`execute_trade\` also treats \`pyramid_long/pyramid_short\` as increasing \`market_open\` orders; a cutover that only handles \`open_long/open_short\` would leave an increase path uncovered. Existing close logic may invoke \`market_close(coin)\` without \`sz\`; the SDK can infer and request the entire account-level position. These paths must be treated as unsafe for shared ownership, even where an SDK call is reduce-only.

## Smallest security-correct future change boundary (proposed only)

1. **Separate read-only information from signing.** A future bot-side client initializer must obtain prices, market metadata and account snapshots without requiring or accessing \`HL_PRIVATE_KEY\`, \`Account.from_key\` or a signer-backed \`Exchange\`. Pin the **effective master/sub-account** independently of API-agent wallet identity. Decide how operator-approved account read scope is distributed; no caller-selected account.
2. **Single, separately authenticated trading sender.** Keep trading credentials only in the isolated coordinator/sender service, never bot Actions jobs. Restrict service ingress to independently authenticated Daily, Intraday and Aggressive identities. Remove competing usable order-signing paths and verify credential revocation/absence at runtime, not only by searching imports.
3. **Preserve exact strategy intent.** Leave signal, size, leverage, minimum-notional, TP/SL and kill-switch calculations unchanged. Submit a **strict desired-action request** to the central sender; bot requests must not be an executable trade, an authorization token, a raw SDK payload, or a grant to release claims. Require reviewed treatment for Aggressive pyramids and leverage changes, not just fresh entries.
4. **Commit the binding before dispatch.** A restricted coordinator must atomically persist independently verified bot identity, effective account/environment/DEX/coin, rounded exact decimal quantity, action, durable token/fence, unique immutable 128-bit CLOID and pre-submit baseline. The previously blocked SQL privilege/CLOID change is **not** implemented; do not work around that block.
5. **Serialize every mutation.** A single writer must control open/increase, leverage changes and an independently reviewed close path under the correct account scope. Never allow a direct \`exchange.market_open\`/unsized \`market_close\` fallback in a bot worker. Each approved close must have a positive explicitly bounded size, independently reconciled owner, matching direction and reduce-only semantics.
6. **Unknown outcome blocks reuse.** Commit a durable attempt marker before the exchange send. On timeout, crash, missing OID, partial fill or conflicting account activity, HOLD; do not automatically retry a CLOID, adopt a same-side position, release a claim, or assume another bot may safely send.
7. **Trusted evidence reader remains separate.** An isolated, read-only collector must verify the actual request/response transport and gather order status, fill history, open orders, position snapshots and manual/other-agent activity. Existing synthetic collectors prove **no** authenticated origin, no exchange history completeness and no authorization.
8. **Plan legacy and emergency behavior first.** Preexisting positions lack trustworthy pre-submit attribution; quarantine pending explicit operator handling. Decide emergency stops, protective closes, strategy behaviour during HOLD/outage and rollback without silently changing TP/SL or kill switch. Under a sender outage, automatic protection may be unavailable; that is a **trading risk** requiring approval, not a harmless test choice.
9. **Coordinated all-three cutover only.** No partial switch where one bot uses the sender and two retain signer access. Halt conflicting order creation, review unresolved claims and existing positions, deploy only with independently tested credential/ACL isolation, then observe with an approved testnet account after separate permission. Reverting to direct senders while unknown orders remain is forbidden.
10. **Independent production approval.** Review the exact diff affecting each executor, shared \`get_client\` helper, workflows, keys, database privileges, separate sender, read-only transport and operator fallback. Require security and trading-risk sign-off; green offline CI alone is insufficient.

## Release-blocking checks for future implementation review

- A bot process cannot read \`HL_PRIVATE_KEY\`, import/use the signing client, or reach a usable exchange signing endpoint.
- All three bots (and Aggressive pyramid actions) route **all** mutating requests through one reviewed account-scoped writer; \`update_leverage\` is included.
- No call site can submit directly on failure/timeout or close an attributed position without an explicit reviewed positive size.
- A stale worker cannot send after its fence changes; an uncertain send blocks reallocation through restart.
- Separately authenticated account history covers the pre-submit baseline and all same-coin netting; unproved legacy ownership stays HOLD.
- CI OS/DB isolation checks are backed by independently verified deployment identity, egress policies, credential permissions, failover/rollback and real read-only provenance.
- Dedicated testnet activity, production credentials/permission changes, merge and deployment **each need explicit subsequent approval**.

**Decision: live NO-GO.** Existing PR #40 simulation, one-process read-only fixtures, and distinct-UID file ACL tests are useful but do not satisfy these cutover gates. The next implementation stage should be a **small, independently reviewable signer-free bot client / single-sender interface design**, rather than more overlapping fake fill tests.
