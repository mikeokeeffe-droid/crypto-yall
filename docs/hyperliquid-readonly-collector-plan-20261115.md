# Hyperliquid read-only collector design — deployment NO-GO

**15 November 2026. This is an offline request PLAN, not an HTTP collector.**

The module `sender_review/hyperliquid_readonly_collection_plan_offline.py`
constructs synthetic, explicitly non-executed POST `/info` envelopes for
the testnet host. Its allowlist covers clearinghouse state, open orders,
historical orders, time-bounded user fills and order-status lookup. No signing
keys, SDK, HTTP transport, database credentials or operational accounts are
used. Every returned result is HOLD.

The query plan is a design aid, not a guarantee that the named API response
schemas, filters or historical coverage are suitable for account-wide
reconciliation. The live collector must be built and independently tested
against official endpoint definitions before testnet network access.

## Risk: provider retention windows

Official Hyperliquid API documentation indicates that historical orders
are limited to the most recent 2,000 orders. The time-based fill endpoint
returns at most 2,000 fills per response and exposes only the 10,000 most
recent fills. These caps mean that no API success, short page, early
startTime or caller's `historyComplete=true` claim establishes a complete
historical provenance chain or an initial flat account.

A production design needs an independently maintained, durable archive,
verified checkpoint, real account-wide ownership policy and completeness
audit. Without those, legacy/manual position attribution remains unknown.
Do not close or assume ownership of a position merely because a matching
CLOID or a self-reported bot label is found.

## Future runtime isolation requirements

- Separate read-only process/identity with no `HL_PRIVATE_KEY`,
  `eth_account`, signing wallet or exchange order API access
- Egress allowlist enforced outside the process, fixed target hostname,
  certificate validation, bounded timeouts/retries and no arbitrary URLs
- Explicit response-size/time/pagination limits and schema validation;
  never treat truncated history as complete
- Atomic or otherwise independently reconciled order/fill/position
  checkpoints with handling for concurrent and manual trading
- Durable server-owned nonce/fence and account-wide single-writer policy
- No grants from a read-only collector to issue or retry orders;
  an unrelated and independently reviewed signer boundary is still missing
- Deployment review and operator authorization required before even
  testnet read-only network tests

**Status: PR #42 draft. No testnet or live deployment; live trading NO-GO.**
