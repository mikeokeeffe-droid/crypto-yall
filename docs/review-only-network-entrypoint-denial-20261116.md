# Draft review-only network entrypoint denial — 16 November 2026

**PR #42 draft • NO TESTNET NETWORK ACCESS • NO TRADING • independent security review pending**

## Why this safety change was necessary

Several draft proof-of-concept functions could previously attempt outbound
HTTPS when passed an ordinary boolean flag set to `True`. The helpers were
review-only, and none of the three original production bot workflows invoked
them, but a caller flag is not a valid host-security authorization boundary.
An independent reviewer has **not** approved testnet egress, credential
isolation or a specific public testnet account; the host UFW and Hetzner
firewall permit outgoing connections by default.

## Changes on the draft PR (source code, not the server)

These public entrypoints now **return HOLD regardless of caller inputs**:

| Module | Entry point | Networking now |
|---|---|---|
| `coordinated_testnet_readset_review.py` | `inspect_coordinated_testnet_readset_transport_review` | Never |
| `hyperliquid_testnet_readonly_snapshot_review.py` | `inspect_testnet_info_readonly_snapshot` | Never |
| `hyperliquid_testnet_recent_history_review.py` | `inspect_testnet_recent_history_review` | Never |
| `github_oidc_public_keys_transport_review.py` | `review_github_public_jwks_transport` | Never |
| `github_runner_oidc_handoff_review.py` | `request_runner_oidc_token_review` | Never |

The old unapproved transport helpers for the four-frame snapshot, bounded
history, JWKS discovery and runner token retrieval have been removed from
these draft modules. **Even passing `enabled_readonly_testnet_network=True`,
`approved_readonly_network=True` or `explicitly_enabled=True` grants no
HTTP access.** No caller-selected URL, trading signer, private keys,
exchange `/exchange` route or database-write permission was added.

**Preserved offline validation:** position and open-order parsers, bounded
order/fill consistency checks, strict duplicate-JSON validation, pinned
URL *syntax* validation, and the six-frame local read-set reconciler. Tests
now exercise these pure functions and assert the exported compatibility APIs
remain HOLD. Successful offline fake-data consistency still cannot establish
account control, history completeness or order ownership.

The existing **PR #41** offline-only collector remains unchanged and
network-denied. The **three original Daily/Intraday/Aggressive workflows**
and actual Hetzner test host were **not modified** by these PR #42 edits.

## Still required before ANY real read-only testnet request

1. Independent and verifiable review of code, imports/dependencies,
   active runtime identity, privileged sockets, inherited credentials,
   actual namespace firewall/egress policy and recovery plan.
2. Design and deploy a **separate**, restricted-egress network-capable
   collector after a code and host-security review, with TLS hostname,
   DNS, proxy and IPv4/IPv6 bypass controls. Keep the currently installed
   offline unit and UFW/Hetzner settings untouched.
3. Separate explicit operator authorization for one fixed public testnet
   account, exact `/info` request list, bounded request rate/time and
   evidence retention. A new reviewed transport implementation would
   require its **own** CI and independent sign-off.
4. Never infer authority to sign, create or close orders from an authenticated
   HTTP response or local reconciliation. Protected sender cutover remains
   separately gated.

**Decision: TESTNET / LIVE NO-GO.** Passing offline CI does not change this.
