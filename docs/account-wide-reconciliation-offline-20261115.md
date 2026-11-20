# Account-wide ownership reconciliation — offline fixture review

**15 November 2026. REVIEW ONLY — no exchange connection, signing or trading.**

`sender_review/account_wide_reconciliation_fixture_offline.py` joins
synthetic account-wide positions, orders, fills and bot ownership claims.
The inputs are **not authenticated** and its only output state is `HOLD`.

The fixture checks that all order/fill/position records are present,
come from a claimed flat baseline, and are recent. It rejects duplicate
order IDs, CLOIDs, nonces and fill IDs; manual/unattributed or unresolved
orders; position amounts that do not reconcile to signed fill quantities;
competing bot claims; incorrect account, side, position reference or fence;
and close sizes that exceed a matching synthetic position.

Even internally consistent records **do not establish real ownership**.
The synthetic bot labels, completeness markers and baseline are assertions
from the fixture. The code cannot authenticate them against Hyperliquid.
A stale, incomplete or ambiguous history requires operator investigation,
not a guessed ownership transfer or blind close.

## Independent runtime requirements still missing

- Verified GitHub workload authentication and protected service transport
- Independently fetched, trusted **account-wide** order/fill/position records,
  including manual activity, legacy fills and all previously held positions
- Clear baseline and position attribution policy, including netting,
  cross-bot claims, partial fills, stale reads and abandoned/unknown ACKs
- Durable one-writer fencing, unique order IDs, independent persistence and
  replay prevention across restarts
- Verified current position quantity, precision and exchange-native
  explicit-size **reduce-only** closing semantics
- Safe outage response, monitoring and operational escalation; a blanket
  HOLD alone does not protect a position that is already open
- Independent security and risk signoff, separate testnet approval, and a
  coordinated migration removing all original GitHub signing secrets and
  outbound exchange-order paths

**Result: only a static, offline consistency exercise. PR #42 stays draft.
Testnet and live trading remain NO-GO.**
