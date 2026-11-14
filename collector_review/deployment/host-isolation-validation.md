# PR #41: independent offline Linux host-isolation validation

**Status: OFFLINE STAGING EXERCISE COMPLETED ON TEST HOST — INDEPENDENT SIGN-OFF PENDING; NO NETWORK DEPLOYMENT APPROVED.**

This is an operator handoff for a **new, disposable Linux systemd host**.
It must not be used on the machine, image, account, or runner containing
the Daily, Intraday or Aggressive trading executors, live signing credentials,
or their databases. No collector transport is enabled by this plan.

The source in PR #41 has a disabled network transport. Its existing unit
template runs an **offline host probe plus unit tests only**. The template
cannot be installed by GitHub CI and has no [Install] section.

## Gate A: independently identify a host and reject unsafe placement

Before any host-side operation, a human reviewer must record:

- Host owner, OS and systemd version; verified **separate** from trading bots.
- The proposed unit's immutable, reviewed code revision and root-owned,
  read-only working directory, without symlinks or user-writable ancestors.
- Actual mount and file access boundaries; confirm there are **no** wallet
  files, private keys, seed phrases, exchange API tokens, production DB
  credentials, cloud service credentials, or sensitive Unix sockets available.
- An OS-enforced policy for no outbound networking (not just a Python flag),
  verified by a reviewer independent of the process being checked.
- Exact host-security test procedure, rollback owner, and evidence retention
  location **outside** the service. Never record credential values.

**STOP** if any item is unknown, if the host is shared with a live executor,
or if a network or credential exception is requested.

## Gate B: static validation; safe only on the dedicated staging host

Confirm the systemd unit text is the reviewed
\`collector_review/deployment/testnet-collector-offline-review.service.example\`.
Check that it has exactly the intended two ExecStart commands (host probe
then offline tests), *no* network-enabled collector entrypoint, and:

- \`DynamicUser=yes\`, \`NoNewPrivileges=yes\`, empty ambient/bounding caps.
- \`PrivateNetwork=yes\`, \`RestrictAddressFamilies=AF_UNIX\`,
  \`IPAddressDeny=any\`.
- \`ProtectSystem=strict\`, \`ProtectHome=yes\`, \`PrivateDevices=yes\`,
  \`SystemCallFilter=@system-service\`.
- No EnvironmentFile/LoadCredential, writable paths, sudo escalation,
  custom sockets, background restarts or [Install] section.
- Pin the systemd package version and capture any \`systemd-analyze verify\`
  errors; a successful parse is **not** proof of enforced isolation.

The systemd example references \`/opt/crypto-yall\`, which is only a
placeholder. Preparing that directory and installing a unit require a
*separate explicit operator approval* and root-owned source inspection.
CI runs the static verifier without installing or starting the unit.

## Gate C: actual offline sandbox exercise (requires approval)

On the **dedicated approved host only**, an authorised operator may stage
reviewed code and install the offline *oneshot* service with tightly
controlled file ownership; the service has no [Install] section. Before
running, independently inspect the exact effective systemd directives, any
drop-ins, the service user/group, writable mount points and executable path.

The first ExecStart must execute
\`python3 -B -m collector_review.host_isolation_probe\` *inside the same
unit sandbox* as the offline tests. Expected successful evidence is a real
process in the intended cgroup with non-root UID/GID, no effective/bounding
capabilities, \`NoNewPrivs=1\`, seccomp filter, and a network namespace
different from host PID 1. Any \`collector_host_probe=hold\`, missing log,
execution error, or unexpected environment requires **STOP**.

Run a separate privileged inspection of applied systemd unit properties
and host firewall/egress policy. The probe does NOT independently verify
external egress, secret-file ACLs, or all network namespaces. Do not treat
\`host_candidate\` as proof of egress isolation or permission to read a real
Hyperliquid account. Record redacted logs, unit config, reviewed commit,
OS/systemd version, independent findings and reviewer sign-off.

If this disposable exercise fails, restore the host snapshot / remove the
staged unit and file tree; do not weaken protections merely to make the
probe pass. Do not add a self-hosted GitHub runner on the trading machine.

## Gate D: separate approval for any subsequent testnet request

Only after independently passing Gates A–C may the user separately
authorise a **named public testnet account**, allowed \`/info\` request kind,
one-shot window, rate limits and no-credential runtime for a future
code-reviewed collector network implementation. That is a separate
pull request and security decision; the current PR's network entrypoint
must remain fail-closed.

A real read-only response does not establish exchange ownership, history
completeness, or any right to create/modify orders. No merge, live trade
deployment or shared production controller is authorised by this document.

## Evidence / decision record — observed on test host 14 November 2026

Operator-provided Termius and Hetzner screenshots from `ubuntu-4gb-hel1-1`
(project `crypto-yall-offline-test`). These are observations, **not**
independent reviewer sign-off or proof of absolute absence of credentials.

| Evidence | Current state |
|---|---|
| Named dedicated host and OS | `ubuntu-4gb-hel1-1`, Ubuntu 26.04.1 LTS; systemd package version not separately recorded |
| Local source review / ownership | `/opt/crypto-yall/collector_review` root-owned, ordinary files 644, directories 755; `find -xdev` found no symlinks or group/world-writable entries |
| Git-reviewed host probe | protected file verified against Git blob `c8dc23e83888414971f5d311d653bef88fc6323c` |
| Actual systemd oneshot | `collector_host_probe=host_candidate`; `Ran 16 tests`, `OK`; `Result=success`, `ExecMainStatus=0`; later `ActiveState=inactive`, `UnitFileState=static` |
| Effective unit sandbox settings | `DynamicUser=yes`, `NoNewPrivileges=yes`, `ProtectHome=yes`, `ProtectSystem=strict`, `PrivateDevices=yes`; `PrivateNetwork=yes`, `IPAddressDeny=any`, `RestrictAddressFamilies=AF_UNIX`; no namespace-sharing paths |
| Namespace comparison | host probe found expected *candidate* private net namespace; operator-staged PID 1 namespace reference owned by root with mode 644, parent mode 755 |
| Systemd configuration exposure | `systemd-analyze security` reported 1.9 (OK); informational score, not a deployment gate |
| Socket creation negative tests | Separate transient services first blocked AF_INET and AF_INET6 with Errno 97; on 14 Nov 2026 at 11:02:49 UTC the updated **actual offline oneshot unit** emitted `collector_ipv4_socket_denied=true`, `collector_ipv6_socket_denied=true`, `collector_ip_socket_probe=pass`, preceded by `collector_host_probe=host_candidate`, and ran 16 offline tests. This is socket-creation denial evidence, not comprehensive egress proof |
| Filesystem negative tests | **separate transient services** with similar restrictions returned `home_access=False`, `root_access=False`, `collector_writable=False`; these are selected-path checks, not complete filesystem ACL validation |
| Credential configuration / inventory | no credential-loading or extra path directives found in reviewed unit text; filename-pattern search found zero hits in /home, /root, /opt; neither establishes credential/secret-socket absence |
| Hetzner firewall | `collector-test-firewall` applied to one named test server; inbound SSH 22/ICMP; **outbound unrestricted by this firewall** |
| No automatic activation | `TriggeredBy=` empty; `UnitFileState=static` and `ActiveState=inactive` on last check |
| External egress enforcement | **NOT INDEPENDENTLY VERIFIED** for actual collector; probe explicitly reports `network_egress_verified=false` |
| Independent host security sign-off | **NOT PROVIDED** |
| Explicit named testnet account and one-shot approval | **NOT PROVIDED** |
| Current PR network/submit authority | **DISABLED / NO-GO** |

These tests are limited to the observed configuration and paths. Neither the
temporary sandbox probes nor the low systemd exposure score establishes
network isolation for all possible transports, full secret non-access,
request provenance, or permission to connect to any exchange. The tested
oneshot executes offline checks only.

**Decision:** Document the offline staging milestone. Do not enable network
transport, merge PR #41, deploy live trading bots, or grant testnet account
access without a separate, explicit review.

## PID-1 namespace permission failure observed on disposable staging host

On 13 Nov 2026 the offline oneshot probe returned `hold` because the
unprivileged runtime could read `/proc/self/ns/net` but could not read
`/proc/1/ns/net` (`Permission denied`). This is not permission to disable
the check or run the collector as root.

A *candidate* fix in this draft permits a separately prepared reference
file at `/run/collector-review-host/netns` only when the direct PID-1
namespace read is denied. The probe demands a regular, single-linked,
root-owned, non-group/world-writable reference, root-owned parent directory,
and a valid `net:[digits]` value. Missing or invalid reference remains HOLD.
It compares against the sandbox's own netns as before; a different ID is
necessary, not sufficient, evidence of network isolation.

Only after confirming this is a dedicated, credential-free staging host,
the operator may independently capture PID 1's namespace identifier as root
and stage it with an atomic, root-owned install in a private runtime directory.
Do not copy a value from this document, invent a namespace ID or fetch it from
the isolated collector process. Review the *actual* effective unit properties,
mount permissions and firewall policy separately. A matching namespace check
must never be treated as proof of disabled network egress.

**Updated result (14 Nov 2026):** corrected probe passed in the actual offline oneshot sandbox, with `host_candidate` and 16 offline tests passing; independent egress and credentials review remains outstanding. Keep NO-GO.

## Proposed in-unit no-connect socket-denial test (draft, not installed)

After the 14 November offline sandbox review, PR #41 adds a distinct
`collector_review.ip_socket_denial_probe` program and a **third offline
ExecStart** step in the service example. It deliberately attempts only
`socket(AF_INET, SOCK_STREAM)` and `socket(AF_INET6, SOCK_STREAM)`, with
no `connect`, `bind`, `send`, DNS lookup or HTTP transport. The check
must return HOLD if either socket unexpectedly opens. It runs after the
existing host isolation probe and before the offline test suite.

The already-installed systemd unit is **not automatically updated** by this
draft. Do not mistake passing GitHub unit tests for runtime evidence from
Hetzner. After CI and an explicit operator-approved, reviewed unit update,
the new diagnostic can provide narrow evidence of address-family enforcement
**inside the actual oneshot sandbox**. It still cannot establish absolute
absence of all external egress paths, file-secret exposure, or authorization
for testnet requests. Keep the collector offline and live trading NO-GO.

## Observed in-unit socket-denial check — 14 November 2026, 11:02:49 UTC

Operator-supplied journal screenshot for the reviewed offline oneshot on
`ubuntu-4gb-hel1-1` showed the three-step unit run:

- `collector_host_probe=host_candidate`
- `collector_ipv4_socket_denied=true`
- `collector_ipv6_socket_denied=true`
- `collector_ip_socket_probe=pass`
- `Ran 16 tests` and systemd `Finished ... OFFLINE sandbox review`
- Post-run `ActiveState=inactive`, `Result=success`, `ExecMainStatus=0`

This supersedes the earlier *proposal-only* status for the in-unit socket
probe. It confirms the intended address-family restriction applied to this
process during that run. The probe **does not connect** to a remote endpoint,
so its `network_egress_verified=false` status remains unchanged. Secret
and socket availability, network paths other than these tested AF_INET /
AF_INET6 socket creations, host-level egress control and independent reviewer
sign-off remain separate unresolved gates. Do not enable networking, merge,
connect to Hyperliquid, or authorize trading based on this result.
