# Independent host evidence collection and security handoff

**15 November 2026 — DRAFT, NO-GO. No host inspection was performed.**

The review-only Python module `sender_review/host_evidence_request_offline.py`
produces **textual suggestions**, not executed commands. Every requested
item is `NOT_COLLECTED`, and every approval and deployment flag remains
false. It refers to the existing named
`testnet-collector-offline-review.service` for potential future inspection.
Do **not** install or start any unit to satisfy this worksheet.

## Evidence to collect privately on the correct host

The operator and an independent reviewer should confirm the host's identity,
running service and deployed commit before comparing any command results.
The module includes two narrow, read-only queries:
`systemctl show` of selected sandbox/egress properties, and
`systemd-analyze security` of the identified unit. These show configured
properties or a heuristic score; neither proves an actual credential-free
service or effective firewall isolation.

The reviewer should separately inspect operating-system identity, network
policy, secret and database privileges, OIDC provenance, durable request
replay state, authenticated exchange history, the five legacy execution
paths, emergency protection, rollback and independent approvals.

**Never paste or commit:** private keys, access tokens, `Environment=`
or `EnvironmentFile=` values, `LoadCredential` payloads, database
connection strings, bearer JWTs, host credentials, full unredacted process
environment, raw journal logs or personally identifying operational data.
Secrets should not be sent to GitHub issues, pull requests or this chat.
Share only reviewed, redacted summaries and hashes with appropriate access
controls. Avoid full `systemctl show` output.

## Independent host-review intake (prepared, not performed)

The **host operator** must nominate the actual, approved review-only host and
an **independent reviewer** must confirm its identity. This handoff does not
identify the host, claim access to it, or request that someone access a legacy
server they do not administer. No automatic host inspection is part of PR #42.

| Review field | Present state | Required independent evidence |
| --- | --- | --- |
| Exact host identity and approved operator | NOT_COLLECTED | Private, verified host inventory and operator authority |
| Exact source commit and deployed artifact digest | NOT_COLLECTED | Independently compared source and on-host measurements |
| Effective service isolation | NOT_COLLECTED | Verified target unit/drop-ins, process account, sandbox and mount boundaries |
| Network and egress isolation | NOT_COLLECTED | Actual host firewall/proxy/DNS controls and negative access checks |
| PostgreSQL 18 role and socket privileges | NOT_COLLECTED | If an isolated test database is separately approved, verified local socket group/mode, role memberships and effective ACLs |
| Credential and key exclusion | NOT_COLLECTED | Private assessment that no trading keys or write-capable credentials are reachable |
| Risk operations and emergency exit | NOT_COLLECTED | Human risk-owner review and separate observed rescue/rollback drills |
| Independent signoff | NOT_COLLECTED | Signed decision bound to exact code and host, not to GitHub CI alone |

**Required report format:** a private, access-controlled review record should
identify the reviewer, review date, exact source commit, host/artifact digest,
each finding as PASS/FAIL/NOT_VERIFIED, non-secret evidence references, and
unresolved blockers. A missing field is **NOT_VERIFIED**, never PASS.
Only a redacted summary of this record may be linked to the PR, after checking
that it contains no secrets, internal credential paths or personal data.

**Stop conditions:** host identity unconfirmed; no authorized operator; missing
reviewer independence; unidentified effective socket group or unintended group
members; accessible signing keys; unverified egress; mismatched artifact hash;
unexpected privilege grants; missing risk rescue plan; or any unknown order /
position state. Do not install a service, loosen policy, provision the database,
allow testnet traffic, or submit an order to try to satisfy this handoff.

This is a preparation step only. Its completion does **not** change any of the
fourteen `UNVERIFIED` gates or authorize a merge, testnet deployment, or live
trading.

## Evidence disposition

All fourteen deployment-readiness gates in
`sender_review/ci_only_deployment_readiness_manifest.json` remain
`UNVERIFIED`. The host-evidence worksheet is **not** an attestation.
A reviewer must compare actual measurements, exact deployed artifact
digest, code commit, runtime configuration and the operational rollback
plan before signing a separate security decision. Testnet connectivity
requires separate explicit authorization; live trading requires yet
another independent approval.

This handoff does not check the current host, perform HTTP reads, alter
systemd or firewall configuration, request a secret or grant trading
authority.

**PR #42 stays DRAFT. LIVE and TESTNET networking remain NO-GO.**
