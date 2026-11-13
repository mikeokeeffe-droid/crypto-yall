# PR #41: independent offline Linux host-isolation validation

**Status: PLAN ONLY — NOT PERFORMED / NOT APPROVED FOR DEPLOYMENT.**

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

## Evidence / decision record (fill only after real host inspection)

| Evidence | Current state |
|---|---|
| Named dedicated host and OS/systemd | NOT PROVIDED |
| Root-owned immutable checkout and file ACL review | NOT VERIFIED |
| Network isolation applied to **actual** process | NOT VERIFIED |
| Credential-file/secret-socket non-access | NOT VERIFIED |
| Host-side probe output in real unit | NOT RUN |
| Independent host security sign-off | NOT PROVIDED |
| Explicit named testnet account and one-shot approval | NOT PROVIDED |
| Current PR network/submit authority | DISABLED / NO-GO |

Keep PR #40 and PR #41 draft until their separate review gates are satisfied.
