# PR #40 — pinned Hyperliquid SDK 0.24.0 CLOID compatibility audit

**5 November 2026. Read-only source review only / NO-GO for production.** No original executor, installed dependency, wallet, order, workflow, production database, or remote exchange is changed by this document.

## Result — compatible SDK API, incomplete bot integration

**Verified:** `hyperliquid-python-sdk==0.24.0` natively accepts an optional `cloid: Cloid` parameter in all three methods `Exchange.order(...)`, `Exchange.market_open(...)`, and `Exchange.market_close(...)`. `market_open` and `market_close` forward it to `order`; `order` forwards it to `bulk_orders`; `order_request_to_order_wire` encodes it as `"c": cloid.to_raw()` in the signed exchange order action. No SDK dependency upgrade is needed *just to pass this field*.

**Sources inspected directly at the immutable upstream 0.24.0 tag:**

- `hyperliquid/exchange.py` blob `41a2f66b568451208770517d5afd58af724edded`, `order` lines 140–159, `market_open` lines 245–261, `market_close` lines 262–295. https://github.com/hyperliquid-dex/hyperliquid-python-sdk/blob/0.24.0/hyperliquid/exchange.py
- `hyperliquid/utils/types.py` blob `14dc67bd84a9eb23411e5fc9039dcbfd0f086270`, `Cloid` lines 194–220. https://github.com/hyperliquid-dex/hyperliquid-python-sdk/blob/0.24.0/hyperliquid/utils/types.py
- `hyperliquid/utils/signing.py` blob `560414711218560a8aa48b6adee311361a3a4029`, `order_request_to_order_wire` lines 508–521. https://github.com/hyperliquid-dex/hyperliquid-python-sdk/blob/0.24.0/hyperliquid/utils/signing.py

The `Cloid.from_str` constructor wraps the supplied string; the SDK's `Cloid._validate()` checks the `0x` prefix and 32-character payload **length**, but does not itself reject every non-hex character. Therefore any future boundary must separately validate the entire 16-byte hex format, lower/uppercase canonicalization, collision/uniqueness and immutability. A CLOID must be an unpredictable unique order-correlation identifier, not an authentication credential.

**The original three executors currently call `exchange.market_open(coin, is_buy, size)` and close with `exchange.market_close(...)` without a CLOID**, and they do not bind submission to a shared authenticated, fenced, atomic pre-submit claim. Those original calls were observed on `main` on 5 Nov 2026. Nothing in this audit proposes changing their signal/entry/exit decisions.

## Crucial boundaries that remain unproven

1. **Persist before submitting:** An approved coordinator must atomically persist scope, authenticated bot identity, exact requested size/direction, unique CLOID, request ID and fencing token. The earlier attempted CI SQL CLOID modification was blocked by safety controls; it has not been applied.
2. **Check the exact identity at the dispatch edge:** A later adapter would fetch the persisted immutable CLOID and validate the current fence immediately before calling the SDK. The bot's own `owned_coins`, Gist state or claimed `bot` string is not sufficient.
3. **Do not auto-retry unknown orders:** If order submission or subsequent state saving times out or crashes, preserve the unresolved claim and consult separately captured read-only `orderStatus` by CLOID or known OID. Unknown status, duplicate-looking OID, or missing fill history = **HOLD**, not a second order.
4. **Exchange evidence is account-wide:** Even an order queried by persisted CLOID is not proof of complete bot ownership if other agents/manual actions altered or netted the shared position. Require all relevant OID-to-TID fills, fresh account position, archived history coverage, open orders and pre-submit baseline.
5. **Never infer close size from current full account position:** `Exchange.market_close(coin, sz=None)` can use the whole account-level position; reduce-only alone does not make that quantity bot-owned. Any eventual close must be explicitly sized from verified bot-attributed remaining position under a current fence.
6. **No authorization from offline fixtures:** Existing test outcomes `parsed_untrusted`, `review_only`, `handoff_candidate` and matching CLOID strings are structural evidence only. No adapter/collector/reconciler or production migration is approved.

## Next decision gates

- CI-only ownership lineage should be separately reviewed before code changes: independent bot login, account scope, pre-submit baseline, immutable unique CLOID, fence, OID/FID mapping, unknown-outcome and crash policy.
- Separately security-review the future read-only `/info` transport and audit store; the current SDK compatibility audit does **not** contact Hyperliquid.
- Decide how to handle legacy positions without a trustworthy pre-submit CLOID, especially existing same-coin positions or TP/SL triggers while provenance is uncertain. No silent strategy change.
- Any actual original-executor modification, testnet traffic, live order, workflow or production DB change requires a fresh explicit review and approval.

**Status:** SDK CLOID signature compatibility **confirmed**. Independent trade ownership, provenance and production fencing **NOT confirmed**. Keep PR #40 draft and **NO-GO**.
