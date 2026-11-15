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
