# Offline end-to-end collector checks and supervised testnet entry gate

**15 November 2026. PR #41 DRAFT; live trading and real testnet networking remain NO-GO.**

## Source verification completed (limited, concrete)

The operator supplied SHA-256 results from the actual Ubuntu test host for six
files under `/opt/crypto-yall/collector_review`. On 15 Nov, their full hashes
matched the exact UTF-8 file contents at PR #41 commit
`51957b22c7034ff29d9befbda881ad31574d46c8`, 6/6.
The evidence is retained in
`deployment/observed-source-fingerprints-20261115.json` and pinned in
`test_source_fingerprint_pin.py`. This establishes **six file identities at
the time of the screenshots**, not a signed attestation of the host, all
installed files, service file, dependencies, effective execution or runtime
isolation. Subsequent review-branch commits do not silently change the pinned
six originals.

## End-to-end OFFLINE test added

`test_offline_end_to_end_readiness.py` combines canonical synthetic
`POST /info` request construction, strict untrusted-response inspection,
two hash-chained audit events, a validated external digest, rejection of
unauthorized API types and accounts, denied 429 responses, and explicit
TLS/HTTPS mocks proving neither the public entrypoint nor its transport
helper opens a network connection (including when the Python flag is
patched to True). Existing offline history query/response and isolation
tests continue to run in CI. All data are generated in process using
dummy account identifiers: no exchange access, signing, database or host
actions. These tests cannot validate a real production account's history.

## Next supervised TESTNET-only milestone (not approved by CI)

1. Independently review the exact current Git commit plus installed host
   artifact hashes, all Python dependencies, invoked `unittest` modules,
   effective systemd unit and its persistent drop-ins. Confirm a separate,
   dedicated test host (not the trading bot host), root-owned nonwritable
   files and directories, no inherited keys/credentials or privileged
   sockets, and a separate host-enforced allowlist for egress.
2. Independent security reviewer must verify host firewall, namespace,
   DNS, proxy, trusted CA/TLS hostname and response provenance. The host
   previously had unrestricted egress at the provider firewall, so Python
   flags and the systemd 1.9 exposure score are **not** sufficient.
3. Prepare a separately reviewed transport implementation, retaining the
   current intentionally unreachable `_https_post_restricted_review_only`
   unchanged in this PR. Do not simply remove the unconditional
   `PermissionError` or disable `PrivateNetwork` on the existing unit.
4. Collect explicit operator approval scoped to a named **public testnet**
   account, request allowlist, duration, rate limits, evidence retention,
   independent reviewer and exact artifact digest. Real exchange responses
   require authenticated and replay-protected provenance, a completeness
   policy and manual-trade/older-history classification; a shaped HTTP 200
   response is not enough.
5. Only a new separately approved testnet change may make a bounded
   one-shot read-only request; explicitly no `/exchange`, no signing
   key, no DB write role, no market/limit orders and no automatic closes.
   Capture sanitized request ID, canonical body hash, TLS/server evidence,
   response hash, completeness and safe refusal/retry decisions.
6. Evaluate errors, empty history, pagination saturation, stale/missing
   fills, overlapping bots/manual positions, 429, timeouts, disconnects
   and unknown ACK scenarios separately. Only then review live-cutover
   architecture in PR #42, including single signer, true order ownership,
   reduce-only exits, rollback, and independent production approval.

### Mandatory stops

Any unverified source/dependency, host credential availability,
unrestricted effective egress, missing origin proof, missing reviewer or
operator approval, incomplete history, or unexpected execution path =>
**HOLD / NO-GO**. Do not install, enable, start or reboot a service to pass
the source-level tests; do not connect a real exchange or deploy trading
bots. No steps here independently establish any of the 14 protected sender
deployment gates.

The offline CI results may be marked *passed* only when the latest PR #41
commit actually completes green. PR #41 and PR #42 remain draft/unmerged.
