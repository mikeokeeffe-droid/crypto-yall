# Separate read-only testnet collector: proposed trust-boundary decision

**16 November 2026 · PR #41 draft · DESIGN ONLY · TESTNET NETWORK NO-GO · TESTNET ORDERS NO-GO · LIVE NO-GO**

## Decision in one paragraph

**Propose an isolated read-only collector with a separately reviewed,
application-aware outbound gateway.** The collector itself should have
**no general IP route or network capability**, no access to a trading signer,
and no ability to select an arbitrary URL. A *distinct* gateway, not a
collector-controlled HTTPS proxy, would enforce the fixed testnet destination,
HTTP method, `/info` path, bounded request shapes and rate budget.
This is a **candidate design for an independent review**, not an implemented
component, authorized connection, installable unit or approval to trade.

The existing `testnet-collector-offline-review.service` on the inspected
test host remains **unchanged, offline, inactive and manually start-blocked**.
The manually staged source tree's two mismatched test files also remain
unresolved. No changes to old trading bots, existing servers, their
credentials or firewall rules are part of this proposal.

## Why the boundary needs two separately enforced layers

An isolated Linux network namespace or cgroup-enforced deny-by-default
firewall can restrict interfaces and destination addresses, but **cannot
verify the HTTP method or `/info` path inside TLS**. A client that could
open arbitrary TLS over generic 443/TCP could try write-oriented endpoints
on an otherwise approved host. Conversely, an application-level allowlist
implemented solely in the collector is insufficient if the collector can
bypass it through another socket, resolver, inherited proxy, metadata
service or accessible Unix socket.

Both must hold:

1. **Host-enforced reachability restriction:** there is no direct
   collector-to-Internet, host networking, arbitrary DNS/proxy, metadata,
   UNIX-socket-to-proxy or credential-bearing transport path. Enforced
   rules are evaluated on the **actual future service process**, not
   inferred from UFW summaries or installed command names.
2. **Application-aware egress authorization:** the gateway does not act
   as a general-purpose CONNECT/HTTP proxy and does not accept a URL,
   destination IP, path, method, arbitrary request type or authentication
   decision from the collector. It validates the *operator-approved*
   public testnet account, one of the **six fixed** sequential `/info`
   read steps, clock/size/rate bounds and canonical body. Any extra or
   ambiguous field fails closed. It cannot sign or call `/exchange`.

## Proposed separations (not deployment configuration)

```text
Dedicated disposable test host (future only)

 Unprivileged collector runtime:
   no trading secrets / no DB writes / no order client
   no direct AF_INET or AF_INET6 route or outbound socket permission
          │
          │ one tightly scoped, authenticated local IPC interface
          │ (independently review Unix-socket paths, permissions and bypass)
          ▼
 Separate application-aware egress gateway:
   independently fixed testnet host + TLS hostname/certificate checks
   fixed POST /info; exact read-only query-body allowlist
   one public testnet account; limited time, number, response sizes
   deny redirects, tunneling, proxies, all /exchange and write methods
          │
          │ independently restricted TLS egress ONLY to approved
          │ testnet destination and validated DNS resolution
          ▼
     Hyperliquid public TESTNET /info endpoint

 Other accounts, destinations, legacy bot hosts, live wallets and signers:
   NO permitted path or shared secret
```

**Scope caution:** A root/host compromise, overly privileged systemd
socket activation, inherited sockets, shared mount, accessible Docker socket,
gateway implementation flaw, wildcard outbound rule or a proxy listening on
another reachable interface could defeat parts of this boundary. A diagram,
systemd `PrivateNetwork=yes`, a low `systemd-analyze security` score
or a passing offline test **does not prove** the boundary.

## Gateway interface contract for future review

The future gateway must be **separate from this PR's intentionally disabled
network transport**. It must have its own security review and immutable
configuration. It is *not* implemented or called in this PR.

- **Input:** only an authenticated, pre-approved one-shot collection ID,
  exact step number 1–6 and a server-resolved approved public TESTNET
  account. Do not trust caller-provided URL, hostname, HTTP method, path,
  effective environment, headers, JWT assertions or unrestricted body data.
- **Order:** `clearinghouseState`, `openOrders`, `historicalOrders`,
  `userFillsByTime` with one bounded window (at most 24 hours),
  `openOrders`, `clearinghouseState`. Duplicated/out-of-order
  steps and excess requests are denied, not automatically retried.
- **Transport:** fixed `POST https://api.hyperliquid-testnet.xyz/info`;
  verify hostname and full TLS chain, explicitly reject redirects and
  proxy environment fallbacks; reject any `/exchange` URL or
  other path, method or destination. Review trusted DNS and IP changes
  without widening firewall rules.
- **Response:** cap bytes, deadline and error count; deny invalid status,
  malformed response, pagination uncertainty, stale timestamps, gaps
  or account mismatch. Preserve sanitized hashes/timing/provenance only;
  do not log tokens, raw private operational data or inferred ownership.
- **Authority:** no trading key, exchange write credential, production
  DB-write role, signer, general-purpose shell, host administrator socket,
  arbitrary IPC forwarding or remote listener. There is no submit,
  cancel, leverage mutation, close, or retry authorization.
- **Failure:** abort to `HOLD / NO-GO`; do not fallback to a direct HTTP
  client, current offline service, existing trading bots or mainnet.

## Evidence the independent reviewer must obtain (not collected here)

| Gate | Required observation on a *new* testnet runtime | Current result |
| --- | --- | --- |
| G1: code identity | Independently match installed source + dependency hashes and actual executed command to an exact reviewed commit; reconcile 2 staged test-file mismatches | UNVERIFIED |
| G2: host isolation | Effective UID, capabilities, mounts, namespaces, drop-ins, service activation and no inherited credentials/privileged sockets | UNVERIFIED |
| G3: collector egress | Demonstrate denied direct IPv4, IPv6, DNS, metadata, loopback, alternate route and proxy attempts **from inside** the intended collector sandbox | NOT BUILT |
| G4: gateway egress | Independently verify narrow gateway-only egress, TLS hostname, DNS/pinning strategy and denial of broad TCP/443 or alternative targets | NOT BUILT |
| G5: application policy | Test rejection of wrong HTTP method, `/exchange`, redirect, arbitrary URL, unapproved account, malformed/duplicate step and over-budget request | NOT BUILT |
| G6: no authority | Prove neither runtime can access signing keys, wallets, trading bot APIs or production DB write roles; independent negative checks | UNVERIFIED |
| G7: recovery | Named independent security reviewer confirms tested out-of-band console/SSH rollback and bounded shutdown path before policy changes | UNVERIFIED |
| G8: operator scope | Explicit later operator approval pinning exact public testnet account, host, source digest, six reads, time/rate/size limits, evidence retention and abort procedure | NOT GRANTED |

**Do not treat completing G1–G8 as permission for testnet orders.**
Order/fill ownership, partial-fill and unknown-ACK handling, a sole protected
writer, safe explicit-size reduce-only closes and the disabled legacy
writer paths are further independent PR #42 trading-risk gates. Production
requires an additional separate operator decision.

## Mandatory decision before implementation

An independent Linux/network security reviewer must choose and justify either
the **application-aware gateway design above** or an equivalently restrictive,
verifiable alternative. The reviewer must explain how the egress policy
actually enforces HTTP path and method *inside TLS*, how routing cannot bypass
the gateway, how DNS/proxy/UNIX-socket and IPv6 escape paths are blocked, and
how rescue access survives changes. An IP-only outbound rule, `PrivateNetwork`
alone or collector-level `NETWORK_ENABLED` flag is **not equivalent**.

**Do not generate deployable firewall commands, enable a unit, change
`PrivateNetwork`, use `systemd-run` to start a collector, open testnet
network connections, or merge on the basis of this design.** Any real
testnet work requires a new reviewed change after separate, explicit operator
and independent security approval.

**Disposition: proposed design recorded, not deployed. REVIEW/HOLD.
TESTNET NETWORK / TESTNET ORDER / LIVE: NO-GO.**
