# Separate Hyperliquid Testnet public account checker — draft review

**STAGING ONLY. NOT DEPLOYED. NOT APPROVED FOR SERVER EXECUTION. NO TRADING.**

This standalone checker is intentionally separate from PR #41's network-disabled collector,
the existing heartbeat command, and all three existing bots. It is not a replacement
for PR #41's independently reviewed application-aware network gateway.

## Scope

- Fixed host: `api.hyperliquid-testnet.xyz`, HTTPS port 443, TLS certificate and hostname validation.
- Fixed path: `POST /info`.
- Fixed public Testnet account: `0xF14348Bdf59BA186F9CdD0fC5F369e1f6D3b7dC0`.
- Two fixed read-only query kinds only: `clearinghouseState` and `openOrders`.
- Timeout 8 seconds per request; maximum 512 KiB per response.
- No arbitrary URL, account, request type, redirects, proxy environment support, authentication or retries.
- No `/exchange`, wallet, seed phrase, private key, trade signing, database write or order handling.
- Prints only positions and open-order counts, not raw API data.
- No automatic start, service installation, workflow dispatch or schedule.

**Do not run the script on Hetzner yet.** Source-level restrictions alone are not host-level
isolation. Although direct `curl` from the interactive Hetzner login previously reached
Testnet, the protected PR #41 collector service remains explicitly network-blocked.

## Required before any Hetzner one-shot

1. Independent security reviewer to review this exact commit and check that it does not
   inherit wallet/API keys, bot secrets, privileged sockets or production DB access.
2. Confirm a separately reviewed **one-shot** run context, not the collector's
   protected service and not a trading executor. Maintain `testnet-collector-offline-review.service`
   inactive and `RefuseManualStart=yes`.
3. Independently validate outbound TLS/DNS/proxy boundary and no `/exchange` capability.
   The checker itself does NOT enforce process-level egress restrictions.
   Do not weaken existing firewall/systemd controls.
4. Confirm account address, two permitted queries and sanitized output.
   Obtain explicit operator approval scoped to exact reviewed artifact and execution path.
5. Log manual stop/rollback procedure and leave existing trading workflows unchanged.

The GitHub workflow on this branch runs only mocked offline tests. It cannot
connect to Testnet, activate any daemon or place an order.

**Status: Draft; HOLD for execution.**


## Proposed egress contract — OFFLINE REVIEW ONLY

The file testnet_egress_policy_review_only.json describes a proposed **deny-by-default**
security boundary. It is intentionally marked network_authorized=false,
gateway_implemented=false and deployable_as_is=false. Its companion offline
validator and synthetic tests reject requests outside two fixed public Testnet
POST /info frames, including incorrect HTTP methods, arbitrary hosts,
additional accounts, /exchange, excess requests, and authority flags.

**These are design and test artifacts, not enforceable network controls.**
No application-aware gateway, local IPC, independently verified process-level
network allowlist, or service deployment has been built by this PR. A JSON
declaration cannot prevent a malicious program from making an arbitrary
connection if an actual process has unrestricted outbound network access.

The current Hetzner account has broad host outbound reachability; previous
transient PrivateNetwork=yes tests correctly denied direct network access.
Neither fact by itself establishes a safe way to allow only Testnet /info
through a gateway. Independent security review must establish the actual
gateway implementation and enforceable network isolation before any server
network permissions are changed, and a separately scoped operator decision
is required before executing a live one-shot checker.

**Do not** start a gateway, alter server-wide firewall rules, disable
PrivateNetwork on the existing collector, install a scheduled service,
or merge this PR on the basis of passing synthetic policy tests.


## Peer identity review — no real authentication yet

The offline_gateway_peer_admission.py fixture models deny-by-default checks
for an expected unprivileged UID/GID, valid process ID, a single-use review
nonce, rejection of caller-provided identity, and an explicit synthetic
approval flag. Its tests use **fabricated** peer IDs; they do not authenticate
real processes. The nonce is a test constant, not a secret.

Before any real gateway is built or enabled, independent review must establish
a dedicated AF_UNIX socket with restrictive filesystem permissions; actual
kernel-derived SO_PEERCRED validation on the accepted connection; a
host-verified dedicated service/cgroup identity to distinguish other processes
with the same UID; replay and process-restart protections; no user-controlled
claimed identities; and an enforceable separation of network namespaces that
prevents direct bypass. Linux UID/GID matching alone does not distinguish two
processes under the same account. The socket must not be accessible from other
service sandboxes. A real gateway would also need a fixed internal HTTP client,
TLS hostname verification and independent egress filtering.

**Peer admission is simulated only. No socket is opened, no authentication
boundary is active, and no network authority has been granted.** This work
does not authorize the checker, collector, or bot workflows to run.


## Linux kernel Unix peer credentials — offline test only

kernel_unix_peer_review_offline.py can inspect real Linux SO_PEERCRED
values from an **already connected AF_UNIX stream socket**. The tests create
only unnamed local socketpairs and validate kernel-reported PID/UID/GID,
rejection of Internet/datagram sockets and forged Python objects, and
single-use denial in the existing synthetic admission fixture.

This is NOT a gateway. There is no listening socket, socket path, process
allowlist, authenticated approval, TLS proxy, or external network request.
SO_PEERCRED identifies an OS process at connection time but matching UID/GID
does not prove the process is the approved checker, and PID checks alone
may be subject to reuse. Independently review service/cgroup provenance,
same-UID threats, filesystem socket permissions and restart/replay handling
before considering any networked deployment.
