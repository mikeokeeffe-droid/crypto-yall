# Mock Hyperliquid /info collector — offline response parsing

**15 November 2026. Review-only; cannot make network requests or execute trades.**

`sender_review/mock_hyperliquid_info_collector_offline.py` accepts only
scripted `MockInfoReply` byte strings paired with the preapproved
`hyperliquid_readonly_collection_plan_offline.py` query descriptions.
The module has no socket/HTTP client, signing key, exchange SDK,
database adapter, deployed process or credentials. Every outcome is HOLD.

The parser exercises representative shapes for `clearinghouseState`,
`openOrders`, `historicalOrders`, `userFillsByTime` and optional
`orderStatus`, including signed position quantities, order side/size,
CLOID, timestamp, fill identifier and quantity. The tests challenge
malformed, oversized and duplicate-key JSON, HTTP failure, missing or
misordered responses, changed position snapshots, invalid numeric
values, stale/duplicate fill IDs, unmatched orders, overfills and
unresolved/open orders.

**Limitations:** These simplified response examples are not a complete,
independently verified live API schema. A fake matched history is not
authenticated exchange provenance, proof of a flat baseline or
verified ownership of any existing position. Historical endpoint
retention, manual trades, fills falling outside the query range,
partial cancellations and races between observations remain unresolved.
The parser never promotes a response to authority and cannot safely
close or retry an order.

A separately reviewed, credential-free, read-only collector still needs
strict external network egress controls, TLS and hostname verification,
API schema/retention validation, bounded timeouts and paging, durable
authenticated source checkpoints, operator escalation and an account-wide
single-writer handoff with position ownership verification.

**PR #42: DRAFT. Testnet and live trading NO-GO.**
