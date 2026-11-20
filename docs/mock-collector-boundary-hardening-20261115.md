# Mock collector boundary hardening — security review only

**15 November 2026 — NO-GO for testnet and live trading.**

This stage strengthens `sender_review/mock_hyperliquid_info_collector_offline.py`
as a **pure fixture parser**, not an actual Hyperliquid collector.
The only supported input remains an inert scripted series of responses.

## Exact request binding

A caller cannot make an altered request look safe merely by retaining
the `"type": "clearinghouseState"` field. The mock collector reconstructs
the entire canonical testnet `/info` plan with the pinned synthetic account
and compares **all** request envelopes and their selected time window and
optional order identifier.

Tests reject changed account, DEX, query action, unauthorized fields,
altered start time, changed host/path/method, key-exposure markers, an
attempted network call and an order-authority marker.

## Source isolation check

A new source-level test scans the mock parser for forbidden dynamic imports,
process execution, socket/HTTP/SDK/SQL imports, and direct order operations.
This is defense-in-depth, **not** a runtime sandbox or a replacement for
process-level operating-system isolation. A future real read-only collector
must additionally be isolated with an external network egress policy and no
trading secrets, signing capability, writable database credentials or
access to a production exchange order endpoint.

## Remaining blockers

- The parser examines **scripted** bytes, not real authenticated responses.
- Official API schema variants, pagination, retention windows, archived
  baseline, manual orders and concurrent fills still need independent proof.
- A syntactically valid response is not proof of account-wide completeness,
  position ownership, safe reduce-only close size or absence of unseen fills.
- No legitimate API request, signing, protective close, retry, testnet service
  or deployment is enabled by passing CI.

**Result remains HOLD. PR #42 stays draft; LIVE NO-GO.**
