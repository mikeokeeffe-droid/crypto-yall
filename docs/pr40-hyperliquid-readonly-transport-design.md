# PR #40 — proposed genuine Hyperliquid read-only evidence transport (DESIGN ONLY)

Status: **not implemented, not approved for network use or live integration**. This document concerns the ORIGINAL Aggressive, Intraday and Daily bots. It does not authorize merging, deployment, live trades, credentials, production Supabase access, or release of entry claims.

## Purpose and trust boundary

The existing offline fixture parsers validate *shape*, not origin or completeness. A future collector may query the public Hyperliquid `/info` endpoint for order status and fill history **without a wallet signature or trading key**. Public read-only responses are **not proof of wallet ownership**. The configured user address must be the actual intended account/subaccount, not an API-agent wallet; account scope must be pinned independently before any request.

A production-capable implementation needs a separate review and approval. This draft does not add an HTTP client or connect a bot.

## Minimum proposed architecture

1. **Isolated evidence reader**: separate process/module from all order executors, with no wallet private key, exchange secret, signing method, `/exchange` API method, or write access to production trading state. It may produce a review artifact only. Never import a live executor into the reader.
2. **Pinned target**: explicit mainnet/testnet selection, hard-coded official HTTPS host and `/info` path, default perp DEX only initially, pinned user address and exact request type. Disallow custom URLs, redirects, proxy overrides, arbitrary DEX, account switching, and endpoint downgrade. Review network egress controls and TLS certificate verification; avoid relying on untrusted user-supplied `authenticated` flags.
3. **Limited read queries**: `orderStatus` for a known exchange OID and `userFillsByTime` for bounded windows. No trading endpoints. Require a documented request/response mapping, and validate OID, coin, side, original size, timestamps and raw fill trade IDs. Do not interpret `unknownOid` or an empty fill list as no-fill.
4. **Bounded collection**: enforce timeouts, request budget, bounded pages/windows, rate-limit backoff, maximum response bytes, maximum elapsed time, and deterministic failure states. Never retry a write; this reader must have no writes. Record the actual request scope, response capture time, HTTP status and server origin established by the transport; do not fabricate these in a parser.
5. **History coverage**: account for inclusive time boundaries, same-millisecond fills, duplicates, saturation (up to 2,000 per response) and limited recent history (10,000 fills). An empty or short result does not prove older history exists. Require independently reviewed archival evidence for history beyond retention; otherwise HOLD.
6. **Review artifact only**: immutable, redacted record of scope, bounded query windows, transport metadata, parser outcomes, truncation/retention warnings, and unresolved uncertainty. It may be used for human review but cannot unlock a fence, transfer claim ownership, place an order, or certify the entire account flat.
7. **Separation of authority**: any future recovery/claim release needs a separately reviewed policy and independent corroboration from persisted intents, open orders, positions and exchange fills, with stale-worker fencing and crash consistency. None of these are implied by a successful HTTP response.

## Failure handling: HOLD, never silently recover

- TLS/host mismatch, redirect, proxy uncertainty, 4xx/5xx, timeout, rate limit, malformed JSON, wrong account/environment/DEX, unexpected schema, mismatched OID/coin/side/size: HOLD.
- Unknown OID, missing order record, partial fill, conflicting order status, duplicated trade IDs, overlapping/missing time windows, cap saturation, retention uncertainty or archive gaps: HOLD.
- The collector cannot verify wallet ownership from public `/info`; source provenance and ownership are separate questions.
- A successful, correctly scoped read may be labelled **read-only evidence captured** after transport review, but never **history complete**, **no-fill**, **ownership verified**, or **trade authorized** on that basis alone.

## Before implementation / approval

- Independently confirm official Hyperliquid endpoint contracts, rate limits, account/subaccount behavior, fill retention and DEX semantics against current documentation.
- Security review of actual HTTP implementation (TLS, redirects, DNS/SSRF, proxy environment, payload limits, dependencies and egress).
- Tests with synthetic responses first, then a **separately approved** read-only smoke test against a designated non-production account if desired.
- Verify no import path from evidence reader to live executors and no trading-capable credentials.
- Agree on audit storage, access controls, retention, redaction, rollback and operator stop conditions.
- Explicit user approval required before any live request, merge, deploy or production configuration change.

## Existing draft-only offline guards

- `offline_hyperliquid_wire_review.py`
- `offline_hyperliquid_fill_window_audit.py`
- `offline_hyperliquid_retention_gate.py`
- `offline_hyperliquid_readonly_boundary.py`
- `offline_hyperliquid_transport_plan.py`
- `offline_hyperliquid_scoped_fixture_review.py`
- `offline_hyperliquid_capture_provenance.py`

All remain fake/offline checks. Passing CI validates only their tests, not exchange authenticity or readiness for live trading.
