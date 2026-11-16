# Supervised read-only testnet milestone — external evidence handoff

**16 November 2026 · PR #42 / PR #41 · REVIEW ONLY · TESTNET NO-GO · LIVE NO-GO**

## Why this is now the critical path

The three existing bot sizing functions have been exercised against an inert
entry capture and disposable signed-request PostgreSQL journal. PR #42 also
contains a six-frame *read-only* Hyperliquid testnet `/info` transport and
local consistency review (positions → open orders → historical orders →
bounded fills → open orders → positions). Offline CI and fake-data agreement
**do not demonstrate any observed exchange provenance, complete history,
position ownership, an isolated runtime, or authority to trade**.

The next useful result is **independently verified host/network evidence**, not
another copy of the same mock-only validations. Keep PR #40, #41 and #42
separate drafts; do not merge/activate a bot, collector, or signer.

## Known evidence (not enough to approve)

- PR #41 at `8dd5fedd2de676febbdc2e1eedad5f936b908454` describes six
  source-file hashes matching operator screenshots on 15 Nov. This verifies
  those bytes at that observation time, **not** the entire deployed runtime.
- The test host was reported with UFW outbound **allow**, IPv4/IPv6 nft
  output chains **accept** and unrestricted provider egress; these do not
  prove a future read-only service is egress-restricted.
- The existing offline collector is intentionally isolated with
  `PrivateNetwork=yes`, `RestrictAddressFamilies=AF_UNIX`,
  `IPAddressDeny=any` and a fail-closed HTTP helper. **Leave it unchanged.**
- PR #42 at `0d4de69e01ba5e10d770f7abec897c0e0ef86b06` has a
  review-only six-query implementation with optional transport. It is **not
  installed as an approved collector**; passing CI is not deployment approval.

## Independent review packet — evidence to obtain without changing the host

A reviewer **other than the implementer** must verify the exact reviewed Git
commit, all installed source/dependency hashes, the full effective unit and
drop-ins, process user/capabilities, file mounts, inherited environment and
secret absence, relevant service sockets, and the actual runtime's firewall,
namespace, DNS, proxy, IPv4/IPv6 and edge/cloud egress behavior.

Use *read-only observation commands* on the **dedicated disposable test host**,
under a reviewed procedure. Suggested starting points (adjust unit/path to
what is actually installed; do not paste secrets or private environment values):

```sh
git -C /opt/crypto-yall rev-parse HEAD
systemctl cat testnet-collector-offline-review.service
systemctl show testnet-collector-offline-review.service \
  -p User -p DynamicUser -p PrivateNetwork -p RestrictAddressFamilies \
  -p IPAddressDeny -p IPAddressAllow -p ProtectSystem -p ProtectHome \
  -p NoNewPrivileges -p AmbientCapabilities -p LoadCredential \
  -p BindPaths -p BindReadOnlyPaths -p ReadWritePaths --no-pager
sudo nft -a list ruleset
sudo ufw status verbose
```

Commands above **only inspect**; their output alone does not establish effective
per-process egress or a clean credential boundary. Avoid sharing raw
`Environment`, `EnvironmentFile`, private keys, tokens, or DB passwords. Have
the independent reviewer validate these safely on-host.

If the future network-enabled collector is needed, design a **new** narrowly
scoped systemd unit/network namespace (or independently reviewed application-
aware egress gateway), not a weakened version of the existing offline unit.
Host-level allow/deny tests must be performed in that new exact sandbox during
a **separately authorized** controlled test, with safe access/rollback first.
Never change host-wide outbound defaults without a verified SSH rescue path.

## Scope for a future one-time public testnet read (NOT authorized yet)

- Operator must designate the **public testnet account address** and explicitly
  approve the exact code/host, query budget, time window and date after
  independent security review; no production key or exchange write credential.
- Six fixed `POST https://api.hyperliquid-testnet.xyz/info` calls, in order:
  `clearinghouseState`, `openOrders`, `historicalOrders`,
  `userFillsByTime` (one bounded window, max 24 h), `openOrders`,
  `clearinghouseState`. No `/exchange`, redirects, arbitrary host, proxies
  or generic write requests. Respect provider response limits and rate limits.
- Record redacted timestamps, exact outbound request-body hashes, HTTP status,
  validated TLS destination/response provenance, response-body hashes, host
  security evidence and any history gaps. Do not log sensitive credentials.
- All results remain `HOLD` even if the six frames agree. A bounded
  historical order/fill window does **not** prove a flat baseline, older
  manual activity, per-bot ownership, or an atomic exchange snapshot.
- If data is capped, stale, malformed, incomplete, conflicting, inaccessible
  or an unexpected network path is found: stop and classify `NO-GO`.
  No trading, signing, order cancellation, retry, or automated protective close.

## Who must decide what

1. **Independent security reviewer:** sign off actual effective isolation,
   dependencies, egress/ingress/proxy constraints and secret absence for an
   exact source digest and host configuration, or record missing evidence.
2. **Operator:** separately authorize a named public testnet account and one
   read-only experiment, with boundaries and an approved rollback procedure.
3. **Collector reviewer:** independently validate origin, pagination/retention
   and safe archiving; do not attribute an older position based on a match.
4. **Trading-risk reviewer:** only after a verified collector and single writer
   exist, review entry, leverage, Aggressive pyramiding and explicit-size,
   reduce-only protective exits; preserve protections through outages.
5. **Operator again:** separate, later decision for testnet *orders* and,
   much later, for production; no implication from read-only authorization.

**Present decision: STOP / NO-GO for testnet networking and all trading.**
This document does not start a service, change firewall rules, grant
permissions, contact an exchange or assert any independent sign-off.
