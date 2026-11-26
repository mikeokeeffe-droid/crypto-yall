# PR #41 — non-destructive staging and independent review plan

**24 November 2026. REVIEW/PLAN ONLY. Testnet network NO-GO. Testnet orders NO-GO. Mainnet NO-GO.**

## Scope and evidence

The operator uploaded the `pr41-offline-source-inventory` GitHub Actions artifact generated from the PR #41 CI test-merge revision `d05dfd680ff5d552a7d1bb63787d714f4947a771` (the PR source parent is `bd72b0be1e3b1bf6c66f65b2fa20bc1e27d5b8c6`). That ZIP contains a JSON inventory of **28** exact path/byte-length/SHA-256 records and a commit identifier. It does **not** contain the source files themselves, attest to the Hetzner host, or authorize any runtime.

Operator console screenshots of the root-owned, offline collector tree at
`/opt/crypto-yall/collector_review/` show 11 corresponding Python files
and `deployment/testnet-collector-offline-review.service.example` present
(**12** of the 28 inventory paths). Their Git blob IDs were compared manually
with the PR source version; **independent on-host SHA-256 comparison to the
artifact is still needed**, and a screenshot is not an immutable audit trail.

The host additionally has `deployment/observed-source-fingerprints-20261115.json`
(matched to source by Git blob ID) and an **older** version of
`deployment/host-isolation-validation.md` (known Git blob mismatch).
It also has a separate backup file; **exclude backups** from executable or trusted
source. These extras are not part of the 28-file CI manifest.

### Exactly 16 manifest-listed files not present in the operator's listing

- `deployment/offline_source_inventory.py`
- `egress_boundary_review_offline.py`
- `offline_history_query_plan.py`
- `offline_history_response_review.py`
- `six_frame_request_contract_offline.py`
- `six_frame_sequence_review_offline.py`
- `test_egress_boundary_review_offline.py`
- `test_ip_socket_denial_probe.py`
- `test_offline_end_to_end_readiness.py`
- `test_offline_history_query_plan.py`
- `test_offline_history_response_review.py`
- `test_offline_source_inventory.py`
- `test_readonly_host_evidence.py`
- `test_six_frame_request_contract_offline.py`
- `test_six_frame_sequence_review_offline.py`
- `test_source_fingerprint_pin.py`

**Do not confuse source inventory coverage with host authorization.**
The operator reported 27 passing tests among staged offline suites,
and `systemd-analyze verify` did not show collector-specific errors.
Neither result validates an online collector or the future gateway.

## Before staging: no-operation preflight

1. Confirm the exact host is the dedicated disposable offline collector host,
   not a live-bot server. Verify host identity from the independent provider
   console and read the effective systemd unit including *all* drop-ins.
2. Record `ActiveState=inactive`, `RefuseManualStart=yes`,
   `PrivateNetwork=yes`, `IPAddressDeny=any`, restricted address families,
   and no network permissions granted to the collector's service.
3. Check no testnet/mainnet signing keys, exchange write tokens, production DB
   credentials, inherited proxies, forwarded agents, privileged Unix sockets,
   or privileged mounts are available in the proposed service boundary.
   Do **not** reveal credential values in screenshots/logs.
4. Capture directory owner/mode, resolved paths, symlink/mount boundaries,
   service invocation, Python interpreter and dependency inventory.
5. Confirm the source checkout still contains the approved PR #41 commit and
   the CI inventory's test-merge commit is reconciled with that PR's source
   parent. If source changes or manifests drift, STOP for a fresh review.

## Future staging procedure — requires separate operator approval before host changes

- **Do not overwrite or copy into the installed**
  `/opt/crypto-yall/collector_review` tree.
- Stage the **16 missing source files** separately in a *new*, root-owned,
  non-executable review directory on the dedicated host, after approving its
  exact path. Obtain bytes from a **fixed reviewed Git commit**, not from ZIP
  filenames, screenshots, floating branches, or unpinned downloads.
- Verify *all 28* staged source paths against the uploaded artifact's exact
  byte-length and SHA-256 fields. Fail on a missing, extra, duplicate,
  symlinked, writable-by-nonroot, or mismatching file. A Git blob match alone
  is not a substitute for the independent SHA-256 verification.
- Keep the original 12 present files and older host documentation unchanged.
  Reconcile the older documentation by review, not by blind replacement.
- Do not run downloaded code until independently inspected. The future dry-run
  tests must remain **offline** and must not import an active trading bot,
  connect to Hyperliquid, load signing keys, start services or alter firewall
  policy. Preserve sanitized evidence of source hashes and review decisions.

## Independent reviewer gate — currently outstanding

An independent Linux/network reviewer must separately establish:

- Effective service identity, non-writable code paths, root ownership, no
  credential or privileged-socket inheritance, no service activation path.
- OS-enforced denial of direct IPv4/IPv6/DNS/metadata/proxy/UNIX-socket
  bypass on the **actual** future service process, with separate rescue access.
- Independently implemented, application-aware egress gateway; do not make the
  existing intentionally disabled `testnet_info_https.py` transport reachable.
- Fixed and certificate-validated **public Testnet** destination, *only*
  bounded `POST /info` on the six reviewed read-only frames for one later
  approved public Testnet account. Explicitly deny `/exchange`, generic
  proxies, redirects, arbitrary paths, methods, accounts, trading/close
  functions, and credentials.
- Replay protection, strict rate/size/time limits, provenance and history
  completeness checks, negative tests and rollback.
- Review and sign-off recorded with reviewer identity, exact source digest,
  host evidence, risk findings, remediation and explicit **NO-GO/GO** decision.

**Operator approval after independent review is also required** before even a
one-shot external Testnet read-only request. Approval to read Testnet data is
not approval to place orders. Mainnet and the three existing trading bots are
out of scope and must remain unchanged.

## Current disposition

**Prepared plan only**. No source copied, installed or executed by this plan;
no server commands executed; no collector started; no network, trading, or
firewall changes approved. Original PR #41 remains DRAFT / HOLD.
