# Independent host-review packet: offline collector and proposed testnet egress

**16 Nov 2026 • PR #41 draft • OPERATOR OBSERVATIONS ONLY • TESTNET NO-GO / LIVE NO-GO**

## Scope and decision

The reviewed subject is the **dedicated Hetzner test host**
`ubuntu-4gb-hel1-1`, its **existing offline-only** systemd oneshot
`testnet-collector-offline-review.service` and the *separate future*
network-enabled Hyperliquid testnet `POST /info` collector. These are
**different runtimes**. This packet does not authorize turning the current
offline unit into a network client.

PR #41 head at preparation: `f63560c737e366adf8692ed1722b5de6738a01c9`
(offline collector CI + Code Safety Check green). PR #42's protected sender
remains a separate draft. Neither green CI nor operator screenshots constitute
independent security sign-off. Source snapshots may change; reviewer must
bind acceptance to the **actual latest reviewed commit and host artefacts**.

**Present decision: HOLD.** No real testnet HTTPS request, private signing
credential, exchange `/exchange` call, database-write role, automated close,
PR merge or live trading deployment is authorized.

## What the operator actually observed

All below are screenshot / terminal observations, **not independent attestation**.

| Control / evidence | Observation | Accepted as |
|---|---|---|
| Source identity | Original six SHA-256 comparisons matched; on 16 Nov, 11 top-level Python files compared with PR #41, **9 matched and 2 test files differed**. The directory is manually staged without `.git`. | *Partial source comparison*, with unresolved drift; not complete runtime provenance |
| Git provenance | `/opt/crypto-yall` is a manually staged tree, not a Git checkout; `source_sha=null`, `source_worktree_clean=false` | **Unverified** commit/dependency linkage |
| Offline unit lifecycle | `loaded/static`, `inactive/dead`, last result `success`, last exit `0`; `RefuseManualStart=yes`; no triggers listed | Candidate inactive/blocked-manual-start configuration |
| Offline sandbox | `DynamicUser=yes`, `NoNewPrivileges=yes`, `PrivateNetwork=yes`, `RestrictAddressFamilies=AF_UNIX`, `IPAddressDeny=0.0.0.0/0 ::/0`, `IPAddressAllow=`; `ProtectHome=yes`, `ProtectSystem=strict`, `PrivateDevices=yes` | Candidate **offline-service** restrictions, not future networked collector |
| Additional systemd | Empty printed bounding/ambient capabilities; `LockPersonality=yes`, `RestrictSUIDSGID=yes`, `RestrictNamespaces=no`, `MemoryDenyWriteExecute=no`; syscall filter listed | Candidate controls; reviewer must assess effective enforcement |
| systemd exposure assessment | `systemd-analyze security` **1.9 OK** | Static heuristic only, **not** an audit or authorization |
| Unit origin | Main service under `/run/systemd/system/`; drop-in `/etc/systemd/system/.../90-block-manual.conf`; `NeedDaemonReload=no` | Requires reboot/persistence and full unit/drop-in review |
| Credentials | `EnvironmentFiles` omitted by systemd property output; `LoadCredential` and `LoadCredentialEncrypted` show `[unprintable]`; grep of unit text found no named credential directives | **UNKNOWN** secret accessibility, do not interpret `[unprintable]` as empty |
| Trading process isolation | No pattern matches for named trading processes, services, timers, testadmin/root crontabs or system cron references; common credential filename search returned 0; no symlinks found within selected trees | Partial **name/path-based** search only; not absence proof |
| Ubuntu UFW/nft | UFW incoming deny, outgoing **allow**; nft IPv4/IPv6 filter output base policies **accept** | Host-wide egress restriction **not established** |
| Hetzner cloud firewall | `collector-test-firewall` fully applied to `ubuntu-4gb-hel1-1`; inbound TCP/22 + ICMP; **all outbound traffic allowed** | Provider egress restriction **not established** |
| Security sign-off | None supplied | **PENDING** |

The operator's `readonly_host_evidence` packet deliberately reported
`unit_not_running_candidate=true`,
`unit_isolation_settings_candidate=true`,
`unit_restrictions_candidate=false`, `unit_fields_observed=false`,
`unit_properties_missing=["EnvironmentFiles"]`,
`unit_properties_redacted=["LoadCredential","LoadCredentialEncrypted"]`.
It **always** leaves `effective_network_egress_verified`,
`secret_absence_independently_verified`, `reviewer_signed_off`,
`testnet_network_authorized` and `trading_authorized` false.

## 16 November operator evidence update — runtime and source drift (NOT attested)

Additional screenshots from the operator's Termius session show:

- `systemctl show` reports `ActiveState=inactive`,
  `UnitFileState=static`, `RefuseManualStart=yes`,
  `PrivateNetwork=yes`, `RestrictAddressFamilies=AF_UNIX`,
  `IPAddressDeny=0.0.0.0/0 ::/0`, and `NoNewPrivileges=yes`.
  `systemd-analyze security` printed **1.9 OK**; that is only a
  configuration-risk heuristic for the **offline** unit.
- The live unit came from `/run/systemd/system/`; its observed drop-in was
  `/etc/systemd/system/testnet-collector-offline-review.service.d/90-block-manual.conf`.
  `systemctl list-dependencies --reverse` listed only the unit itself,
  `TriggeredBy`, `Triggers`, `WantedBy` and `RequiredBy` printed empty.
  None proves that alternative activation mechanisms are absent.
- The name-filtered service, timer and process checks found no additional
  matching programs at the instant observed. This does not rule out generic
  process names, different schedulers, remote GitHub Actions or other hosts.
- `ip netns list` reported no **named** namespaces. `sudo lsns -t net`
  listed the host namespace (`4026531833`) and an additional one
  (`4026532439`), whose representative process PID 11897 was `polkitd`.
  This is not evidence that the future testnet collector has a restricted
  network namespace. The `unshare`, `nsenter`, `ip`, `nft` and
  `systemd-run` executables were present; tool presence alone proves
  neither permission nor effective containment.
- `git -C /opt/crypto-yall rev-parse HEAD` reported **not a Git
  repository**. A depth-3 `.git` search returned no results; therefore a
  source commit cannot be inferred from that installed tree.
- The full top-level `collector_review/*.py` inventory contained 11
  files. Screenshot SHA-256 results compared against current PR #41 contents
  had **9 exact matches** and the following **two mismatches**:

  | File in `collector_review/` | Operator-reported SHA-256 | GitHub PR #41 size / server size | Disposition |
  | --- | --- | --- | --- |
  | `test_host_isolation_probe.py` | `8369fc62f270d0b9649ed81b888240787d19c74a262ec5868a3d11b28d85a256` | 7223 / 3882 bytes | DRIFT — investigate, do not overwrite |
  | `test_offline_systemd_unit.py` | `82eb59c5a21aa9e0486463410578c4d6eb765eb89b068a3bbe3ced454bd496e4` | 3716 / 3607 bytes | DRIFT — investigate, do not overwrite |

  Both host files were reported modified at **2026-11-13 23:26:52
  UTC**. The copies at `/opt/crypto-yall/` had the same hashes as the
  respective `/opt/crypto-yall/collector_review/` copies. Neither file
  changed between the PR #41 older reference commit
  `51957b22c7034ff29d9befbda881ad31574d46c8` and the branch
  reviewed for this comparison.

**Important interpretation:** These are **test files**, but a mismatched
host source tree is not verified. The screenshots do not demonstrate
tampering; they also do not provide a justification to ignore the drift.
Independently inspect the diff and explain provenance before approving
any artifact, dependencies, runtime, or testnet experiment. Do not
install/replace files on the host just to make hashes pass.

## Single-pass independent reviewer deliverables

The owner must nominate an **independent qualified Linux/network security
reviewer**; the implementer and this assistant cannot self-attest. Reviewer
should gather evidence on the exact disposable host and record date, identity,
host configuration fingerprint, method and supporting redacted references.
Never send private keys, token values, seed phrases, passwords, or raw
environment dumps to chat or PR comments.

**Gate H1 — Artefact and runtime identity (PENDING).**
Independently inventory all installed executable code, Python interpreter and
dependency versions/hashes (including imported packages), user-writable
ancestors, actual invoked files, cgroups, full unit text/drop-ins and
effective `systemctl show` state. Reconcile the manually staged root-owned
source tree with a fixed reviewed source commit using signed or independently
recalculated digests; resolve the **two mismatched test files** and inventory
nested files and dependencies as well as the 11 top-level Python files.
Nine matching top-level hashes are insufficient.

**Gate H2 — Credentials and process separation (PENDING).**
Verify no wallet/exchange signing keys, trading API tokens, privileged Unix
sockets, proxy credentials, production database-write secrets, inherited
environment or host service access are reachable **from the proposed new
collector runtime**. Do not publish file contents or credential locations.
Check services, jobs, containers, namespaces and mounts beyond name-based
searches, including across mount points skipped by `find -xdev`.

**Gate H3 — Future collector egress architecture (NOT IMPLEMENTED).**
Select and security-review a **new runtime** with independently enforced
default-deny outbound access scoped to that runtime (e.g., verified isolated
network namespace/cgroup and gateway). Constrain HTTPS to authenticated
Hyperliquid **testnet** `POST /info` only, with reviewed DNS, proxy,
IPv4/IPv6, loopback, metadata, redirects, alternate routes and socket-bypass
behavior. Host UFW and Hetzner currently allow all outbound traffic.
Broad `443/tcp` egress or relying on a Python feature flag is insufficient.
Keep the present network-denied offline oneshot unchanged.

**Gate H4 — SSH recovery and rollback (PENDING).**
Independently verify a working out-of-band Hetzner console/recovery route,
rollback owner, snapshot/restore procedure and ability to recover remote SSH
before changing *any* firewall or service network policy. Do not set
host-wide `ufw default deny outgoing` or change provider egress ad hoc.
Because the current unit's `FragmentPath` is under `/run`, evaluate
reboot persistence without rebooting as part of this review.

**Gate H5 — Supervised one-shot read-only approval (NOT REQUESTED / NO-GO).**
Only after H1–H4 independently PASS, a separate operator decision must pin
the exact approved commit/artifact, tested host, **public testnet account**,
one-shot date, query types, time-window, request/response caps, audit
redactions, abort criteria, reviewer and rollback. Follow separate
approved supervised procedures. No production keys and no exchange order
submission. Even a successful read set cannot prove complete older history,
position ownership or authority to close positions.

## Reviewer decision record (UNSIGNED; do not prefill)

| Required sign-off | Decision |
|---|---|
| Reviewer identity, organization, date and evidence reference | **NOT PROVIDED** |
| H1 artefact/runtime proof | **PENDING** |
| H2 credential isolation | **PENDING** |
| H3 new collector restricted-egress proof | **NOT IMPLEMENTED** |
| H4 recovery/rollback verified | **PENDING** |
| Security approval for one-shot read-only testnet | **NOT GRANTED** |
| Separate operator approval for named one-shot experiment | **NOT GRANTED** |
| Testnet order/submit or live trading approval | **NOT GRANTED** |

**Important:** A future review outcome must be accompanied by verifiable
external evidence and a separate operator decision. Changing the words in
this file, passing a CI job or seeing a systemd `1.9 OK` score cannot
turn a HOLD into authorization.

## Hand-off links

- [Restricted egress decision](restricted-testnet-egress-design-20261115.md)
- [Host isolation validation and operator evidence](host-isolation-validation.md)
- [End-to-end collector entry gate](end-to-end-readiness-handoff-20261115.md)
- [Protected sender PR #42](https://github.com/mikeokeeffe-droid/crypto-yall/pull/42)

**No modifications to the remote host, live executors, secrets, firewalls or
exchange networking were made by creating this record.**
