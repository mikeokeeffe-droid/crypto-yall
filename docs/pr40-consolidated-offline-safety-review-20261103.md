# PR #40 — consolidated offline safety review (2026-11-03)

**Decision: NOT READY for live connection, claim release, merge or deployment.** This review covers the new Hyperliquid read-only evidence work on the draft branch only. No live exchange calls were performed.

## What is tested

- Strictly scoped, unexecuted `orderStatus` and `userFillsByTime` query fixtures
- Pinned account, environment, default-perp DEX, HTTPS endpoint and read-only request type
- Synthetic HTTP failure, redirect, TLS-claim, origin and payload-size policy
- Strict JSON syntax, duplicate keys and response-shape checks
- Order/fill identity, size, timestamp, trade-ID and contradictory-status checks
- Missing/overlapping/saturated fill windows, retention warnings, partial fills and stale captures
- Fail-closed `hold` on known ambiguities; positive fixtures are labelled `review_only` or `parsed_untrusted`

## Outstanding safety gaps (blockers)

1. **No authenticated evidence source.** All request/response/capture metadata is caller-supplied. A synthetic `tls_verified=True` field is not proof of TLS, server identity or account ownership. A reviewed, isolated transport with independently established provenance is not implemented.
2. **No proven historical completeness.** `userFillsByTime` has pagination and retention limitations. The independent archive gate accepts a synthetic `review_only` claim, not an authenticated, gap-free archive. Never interpret an empty page as proof of no fills.
3. **Partial-fill reconciliation remains non-authoritative.** The new partial-coverage and order/fill checks examine synthetic totals and terminal statuses; they do not prove that no other fills, cancels, open orders, positions or pending submissions exist. No ownership transfer or fence release is allowed.
4. **Account/market scope is intentionally narrow.** Default perp DEX only. API-agent wallet versus master account, subaccounts, vaults, spot and named DEXes require separately reviewed mappings. A valid-looking address is not evidence of the correct trading account.
5. **Transport security not implemented.** No real TLS certificate checks, redirect/DNS/SSRF protection, proxy isolation, rate-limit/backoff, bounded HTTP body streaming, HTTP parser, response capture clock or tamper-evident audit artifact exists yet.
6. **No safe operational integration.** No independent production review of crash/restart handling, stale workers, persisted intent consistency, current positions/open orders, operator stop conditions or audit storage. Draft offline modules must remain disconnected from live executors.
7. **CI is not live validation.** Passing GitHub checks exercises synthetic fixtures and disposable test systems. It does not verify the Hyperliquid API in real time, completeness, production readiness or trading profitability.
8. **Potential evidence ambiguity.** `offline_hyperliquid_order_fill_conflicts.py` deliberately ignores other OIDs in the same parsed account window when calculating this order's filled amount; those other fills may be important for account-level position reconciliation. Do not infer account flatness or safe re-entry from its result.
9. **Timestamp authenticity and units.** Freshness uses caller-supplied millisecond timestamps; a consistent fixture cannot establish a trustworthy clock or server-side capture time.

## Next recommended safe work

- Extend synthetic tests for account-level position changes caused by *other* orders and for a partial fill followed by cancellation/rejection. These should HOLD, never release an entry fence.
- Add a single, clearly documented review-only pipeline test that feeds synthetic JSON through all guards and proves there is no path to a trading-authorized status.
- Independently verify Hyperliquid API contracts and security requirements before writing any real HTTP client.
- Require explicit user approval for any live request, credentials, merge, deployment or production state change.

**No approval implied by this review.** PR #40 must remain draft and unmerged.
