# SOL Testnet first-order release review — 2026-11-26

## Decision: NO-GO for automated /exchange submission

Scope: **only** the separate draft PR #46 Testnet review branch, pinned owner
`0xF14348Bdf59BA186F9CdD0fC5F369e1f6D3b7dC0`, SOL 1x isolated,
up to $20. The legacy Daily/Mainnet-capable executors and production
workflows are **out of scope and unchanged**. This internal code inspection
is **not** a substitute for an independent security approval.

### Confirmed from user-supplied Ubuntu results

- The dedicated Testnet signing wallet matches the Testnet authorised API
  agent, without disclosing the private key.
- Hyperliquid public Testnet SOL leverage was `isolated 1` when checked.
- The entry and separate emergency journals were previously empty.
- The original Daily SOL strategy returned Bear / `liquidate` with no
  fresh SOL buy signal on the completed 2026-11-25 daily candle.
- The public monitoring check reported
  `PUBLIC_TESTNET_FLAT_READ_ONLY_HOLD` and found no positions or orders.
- Fake-exchange and recovery tests passed locally. These are **not**
  demonstrated live stop-loss or emergency-close behaviour.

### Code hardening in this review

1. Entry sender now rejects SDK clients carrying a non-null
   `vault_address` even if their base URL and account appear correct.
2. Entry signer must equal the **pinned authorised Testnet agent address**;
   any arbitrary well-formed non-owner address is insufficient.
3. Entry sender now independently reconstructs the complete original
   Daily SOL **buy-only** synthetic intent, offline signer boundary,
   deterministic cloids and order fingerprint before even preparing the
   single-use journal claim.
4. Both hard activation locks remain `True`, with no sender CLI,
   scheduler, workflow, deployment or new live trading authority.

### Unresolved blockers (release NO-GO)

- **Authenticated user approval is absent.** The current
  `ExactOneShotApproval.operator_approved=True` is an input field, not
  independent authorization or proof of human intent. It is not safe to
  activate based on this field. Final approval must bind exact owner,
  symbol, side, size, maximum notional, TP, SL, code revision, expiry and
  one-shot ID, and be verified through an independent trust boundary.
- **No verified operational emergency exit.** The emergency sender is
  hard-disabled. Fake one-shot IOC closes cannot prove a real
  missing-stop position can be safely closed, particularly after unknown
  ACK, partial fill, network outage, or exchange rejection. A bounded
  reduce-only IOC may not fill. The emergency close approval flag is
  likewise not authenticated.
- **No active independent watchdog.** The new read-only exposure check is
  manually invoked. There is no supervised, tested continuous monitor
  with independently exercised alert escalation while a live position
  might be open.
- **No verified exclusive runner/egress policy.** Single-host SQLite
  protects the known journal, but there is no independently checked
  whole-host process exclusion, service unit, network egress allowlist
  and immutable deploy proof preventing other order clients from
  accessing the same funded owner.
- **ACK is not proof of protective stops.** Exchange `bulk_orders`
  success can still leave live exposure unprotected, canceled, or
  triggered. Independent two-snapshot `/info` review is useful but
  not a substitute for ongoing monitoring and an operational stop response.
- **Fresh valid Daily entry is absent.** The original SOL Daily
  strategy explicitly disallows shorts and its most recently observed
  completed candle did not generate a fresh buy.
- **Independent reviewer sign-off is absent.** This report identifies
  review gaps; it does not certify the system for trading.

### Next safe milestone

Verify corrected code with CI and Ubuntu fake-exchange tests, then
demonstrate the operator-approved *nontrading* emergency-response
procedure. Only propose live Testnet execution in a separate,
independently reviewed release with all above blockers resolved and
a separately authorised **specific** SOL Testnet trade. Never enable
Mainnet, reuse legacy executors, reset journals, or submit a trade to
clear a failing test.

**Current operational instruction:** leave both sender
`ACTIVATION_HOLD` values set to `True`; keep Testnet trading OFF.
