# PR #40 — signer-free bot boundary: next narrow offline implementation gate

**14 November 2026. Draft-only specification; LIVE NO-GO.**
This is a code-review handoff. It does not change executors, workflows,
exchange clients, keys, credentials, account states, DB privileges, or live trading.

## Verified source dependency

At PR #40 head `0e69da798b559da6b8bec14bb0d758babe02312b`:

- `hyperliquid_executor.py:get_client()` reads `HL_PRIVATE_KEY`
  and `HL_ACCOUNT_ADDRESS`, calls `Account.from_key(priv_key)`,
  constructs `Info` and signer-backed `Exchange`, then returns both.
- Intraday and Aggressive both import `get_client` from Daily and call
  it in their `main` startup paths. Therefore the current three bot
  processes are **not** signer-free, even if orders are blocked by Python
  claim checks.
- See `pr40-exact-three-bot-dispatch-cutover-inventory-20261111.md`
  for direct mutating callsites and the unsized-close and pyramid risks.

## Small next implementation step (offline only)

Prepare a separately testable, **default-disabled** prototype interface
that separates:
1. **Market/account-read intent:** receives independently configured
   environment and effective account scope; does not construct
   `Account.from_key` or `Exchange`, and does not load signing secrets.
   For CI it uses synthetic responses and makes zero network calls.
2. **Desired-action envelope:** bot requests are data (signal/action,
   rounded decimal quantity, account scope, strategy identity, reason,
   requested leverage and close parameters), not executable SDK calls.
   The bot cannot claim approval, create a signed order, or release an
   unresolved reservation.
3. **Central sender boundary:** a separate design-only interface that
   always returns HOLD until a reviewed independent single-writer
   signer and protected durable journal exist. No bypass fallback.

## Negative acceptance tests before modifying any executor

- Importing and exercising the prototype must work with
  `HL_PRIVATE_KEY` absent and must never instantiate signer
  or network clients.
- Distinct mock Daily, Intraday and Aggressive identities cannot
  change effective account/environment/DEX scope supplied by the
  coordinator; spoofed identities are rejected.
- Test all order-increasing paths, including Aggressive pyramids,
  leverage updates, closes with omitted size and other SDK mutation
  callsites identified in the inventory.
- Sender outage, stale fencing, unknown send outcome, missing
  provenance, and ambiguous close ownership all HOLD; no direct
  `Exchange` fallback or automatic same-side position adoption.
- Protective exits and kill-switch behavior are explicitly reviewed
  as trading-risk design choices; do **not** silently change them.
- Existing strategy/sizing/leverage/TP/SL calculations and GitHub
  Actions production workflows remain unchanged.
- Offline tests and independent code review must pass before even
  proposing a synchronized three-bot cutover.

## Still-blocking architecture gates

The actual single-writer signer, OS-separated service credentials,
real exchange-order provenance, complete account-level reconciliation,
bounded close-only quantity enforcement, emergency recovery and
independent security/trading-risk approval are **not implemented
or demonstrated** by this specification. The read-only collector
in draft PR #41 remains network-disabled. No production change or
testnet request is authorized.

**Decision: PLAN READY FOR CODE REVIEW; LIVE NO-GO.**
