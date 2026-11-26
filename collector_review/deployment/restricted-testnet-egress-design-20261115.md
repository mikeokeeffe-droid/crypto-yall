# Restricted egress decision for a future Hyperliquid testnet /info collector

**15 November 2026 | PR #41 | REVIEW-ONLY DESIGN, NOT AN IMPLEMENTATION**

## Decision and evidence

On the dedicated Ubuntu test host, operator-supplied terminal observations on
15 November show UFW **active** with default **allow (outgoing)**. IPv4/IPv6
nftables filter output base chains also showed **policy accept**. The grep-based
output did not establish the full applied firewall or effective per-service
routing rules. The upstream Hetzner firewall is documented as permitting
unrestricted outbound traffic. These observations do **not** establish a
host-wide outbound-deny barrier for future network-enabled code.

The currently installed offline oneshot has `PrivateNetwork=yes`,
`RestrictAddressFamilies=AF_UNIX`, `IPAddressDeny=any`, and previously
produced `collector_ipv4_socket_denied=true` and
`collector_ipv6_socket_denied=true` inside its actual service sandbox.
The Python public entrypoint and transport helper both fail closed.
**Preserve this unit as-is.** It is not a network-capable testnet collector.

## Recommended boundary architecture (proposal)

1. Keep the dedicated staging host segregated from Daily, Intraday and
   Aggressive live trading executors, wallets, keys, real exchange API tokens,
   state DB credentials and any self-hosted CI runner with live secrets.
2. For a future, separately reviewed *read-only* testnet collector, design a
   **new** systemd unit and a **dedicated, egress-restricted network boundary**
   (isolated namespace/container + independently managed host/edge firewall,
   or a narrowly scoped reviewed gateway). Do not loosen or repurpose the
   currently installed offline test unit or PR #42's inert fixture.
3. The collector must be able to send only an approved `POST` with canonical
   `/info` request types to the pinned Hyperliquid **testnet** HTTPS
   destination, over TLS with certificate/hostname validation. No
   `/exchange`, other HTTP methods, URL override, redirect following,
   arbitrary hostname, broad `443/tcp` egress, fallback proxy or DNS-driven
   unrestricted destination selection is permitted. If name resolution is
   necessary, define and review its bounded mechanism explicitly. Do not
   assume a destination-IP-only rule guarantees hostname pinning or remains
   correct when service addresses change.
4. Prefer a default-deny outbound policy **scoped to the collector runtime**,
   reviewed with actual namespace, interface and owner/cgroup placement,
   IPv4/IPv6, local loopback, IPv6 alternative paths, metadata endpoints,
   UNIX sockets/proxies, process inheritance and host services in scope.
   A Python `NETWORK_ENABLED` flag, private network namespace alone,
   or summary UFW output cannot substitute for applied network controls.
5. Keep runtime non-root, with no ambient capabilities, no inherited
   credentials, no trading signer, no writable production database role,
   no anonymous remote control listener, immutable/reviewed source bytes
   and a narrowly scoped, separately retained audit log.
6. If a future capture is approved, record an operator-pinned public testnet
   account, allowlisted query type, one-shot time window, request limits,
   canonical request hash, authenticated TLS destination evidence, response
   hash and timestamp. Review data provenance and completeness separately.
   A TLS response or hash-chain alone does not establish account ownership,
   missing order history, or authority to submit/close trades.

## Implementation alternatives to review, without applying changes

| Candidate | Reason to consider | Unresolved risk |
|---|---|---|
| A. Remain offline (CURRENT) | Zero intended exchange networking and existing socket-denial evidence | Cannot independently validate remote exchange provenance |
| B. Separate restricted network namespace with host firewall rules | Potential per-service isolation while preserving SSH and host maintenance | Requires expert review of interfaces, resolver, IPv4/IPv6, routes and actual egress; no rules have been deployed |
| C. Dedicated application-aware egress gateway | Can explicitly constrain HTTP method, host and `/info` path on top of TLS validation | Gateway trust, mTLS/authentication, bypass routes and operational cost must be independently evaluated |

Do **not** change host-wide `ufw default deny outgoing` or the existing
`nftables` policy on the remote machine based on this document. An
ill-planned firewall change may break SSH access, package updates,
monitoring, time synchronisation and emergency recovery.

## Mandatory reviewer checks before any testnet activation

- [ ] Owner attests this is a separate, disposable testnet-only host with
      restoration access independent of current SSH session
- [ ] Reviewer confirms deployed artifact digests and dependency inventory
      against a pinned, independently reviewed commit; **six matching source
      files are insufficient for an entire runtime attestation**
- [ ] Exact systemd and namespace/cgroup effective properties and all
      drop-ins checked; no inherited secret, privileged UNIX socket or
      unwanted writable path accessible
- [ ] Review full OS/cloud firewall rules (not a grep of base-chain policies);
      prove default-deny applies to the **future runtime** and test IPv4,
      IPv6, DNS/redirect/proxy/metadata/loopback bypass vectors
- [ ] Demonstrate denied outbound connections to nonapproved endpoints
      and allowed connection only to approved testnet `/info` from
      *inside* the proposed runtime, during an explicitly approved
      one-shot test; no broad outbound access
- [ ] Preserve SSH/admin access and an independently tested rollback path
- [ ] Named reviewer records sign-off and user separately approves exact
      public testnet account, request type, duration and bounded rate
- [ ] Independently verify origin, history completeness, order identity,
      cross-bot exclusivity and safe UNKNOWN/HOLD handling before any
      order-sending integration

## Status and stop decision

**Egress design: DOCUMENTED; NOT APPLIED. Security reviewer: PENDING.
Testnet network approval: NO. Production trade permission: NO.
PR #41 and PR #42: DRAFT / NO-GO.**

This document is for review only. No host service, firewall, network,
database, exchange endpoint, signing credential or bot workflow is changed.
