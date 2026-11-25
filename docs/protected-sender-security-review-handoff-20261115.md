# Protected sender — independent security review handoff (draft)

**15 November 2026. OFFLINE CI ONLY. LIVE / TESTNET NETWORK NO-GO.**

This note separates *verified offline properties* from proposed production trust
boundaries. It is not a deployment plan or a security approval.

## Current isolated evidence

- `remote_request_boundary_offline.py` checks a synthetic signed GitHub OIDC
  token against pinned repository, repository ID, owner ID, workflow ref,
  audience, ref, issuer, run, and time claims. Its fixture RSA keys and
  time are supplied by the test harness, not a real trusted JWKS channel.
- `request_contract.py` parses an exact entry-only schema. Closes, leverage
  changes, pyramids and extra caller-supplied account/authority fields HOLD.
- `ci_only_identity_bridge.py` inserts nonce and JTI receipts, a journal
  review intent, and exact token/body SHA-256 evidence in one PostgreSQL
  transaction. It currently connects as the disposable CI database
  administrator and MUST NOT be deployed that way.
- `ci_only_journal.sql` holds scope fences after uncertain outcomes and has
  no release or trading authorization. Composite foreign keys now require
  evidence to match one intent on intent ID, network, account, nonce and
  bot, and one fixture identity receipt on account, JTI, bot and nonce.
- `ci_only_restricted_role.sql` demonstrates a NOLOGIN role with no direct
  table privileges. **Crucially, its SECURITY DEFINER entrypoint takes a
  caller-asserted JTI and bot and is not an authenticator.** It must not be
  exposed to untrusted requests, even over TLS.
- CI tests are run only on a disposable loopback PostgreSQL 16 service with
  an artificial account and no Hyperliquid signing/SDK/HTTP access.

## Unresolved blockers that require an independent reviewer

1. **Real issuer trust and protected transport:** independently acquire and
   rotate GitHub Actions JWKS over verified HTTPS, enforce a trusted clock,
   bind the exact runtime GitHub OIDC claims and approved run provenance, and
   rate-limit/size-limit the remote request interface. Reject missing or
   ambiguous headers, expired assertions, altered body, replay and forged
   caller-supplied bot/account identifiers.
2. **Runtime SQL permissions:** the test bridge uses PostgreSQL superuser.
   Design least-privilege, separately owned operational functions and roles,
   audit SECURITY DEFINER search paths and `PUBLIC` grants, isolate schema
   ownership, and prohibit direct table reads/writes by untrusted clients.
   Do not copy the test-only role or SQL into Supabase/production.
3. **End-to-end identity binding:** after independent authentication, bind
   verified workflow identity, immutable issuer claim, request hash, server-
   selected effective account/DEX/network, nonce, immutable risk policy and
   evidence IDs atomically. The DB must never accept a caller's asserted
   identity as authority. A JWT by itself is not a signature of request bytes:
   protect request delivery against token theft, request substitution and
   replay, and scope one-time consumption accordingly.
4. **True single writer:** existing `main` Daily, Intraday, Aggressive
   workflows still expose `HL_PRIVATE_KEY`. Prove the old order sender paths,
   retry branches, leverage mutations, protective exits and pyramids are
   blocked/converted *together* with runtime secret/egress isolation.
5. **Exchange provenance and recovery:** independent account-wide order/fill/
   position reads, legacy position ownership, CLOID attribution, unknown ACK,
   crash-before/after-send, partial fill, stale fence, concurrent manual order,
   network partition and time-skew handling are not yet demonstrated.
6. **Protective close and trading risk:** safe bounded explicit-size reduce-
   only closes, exchange order-size precision, TP/SL, kill switches, low/high
   leverage policy, emergency outage behavior and rollback must be reviewed.
   Never treat blanket HOLD as proof an open position is protected.
7. **Operator authorization:** obtain separate explicit approval for the
   specified testnet account/network and a new independent security review
   on exact commit and runtime host evidence before any testnet network or
   order attempt. Require a further distinct approval for production.

## Hard prohibitions

- No mainnet/testnet HTTPS, no signing wallet, no order SDK call, no deployment,
  no production SQL migration, no merging this draft based on green CI alone.
- Never move an unresolved request to retry/release on a timeout or inferred
  flat position. No blind order retries.
- CI fixtures do not confer real issuer or caller authentication. The
  offline evidence digest is an audit link, not authorization.

**Exit status: REVIEW PENDING. LIVE NO-GO.**
