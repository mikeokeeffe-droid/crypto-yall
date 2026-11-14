# PR #40 — unresolved order claim release evidence (offline review)

**Status: design review only. Not a production runbook, deployment approval, or
instruction to clear a live lock.** Aggressive, Intraday, and Daily remain
unchanged by this document.

## Why a successful-looking response is insufficient

The original executors can classify malformed `filled` receipts as fills.
They can then remove `pending_entry_claims` based on that status. A position
snapshot alone cannot establish which bot submitted an order. A timed-out
request may have reached Hyperliquid even when the client saw an exception.

## Evidence required before considering any future release mechanism

1. **Pinned intent before submission:** durable, unique request/intent ID;
   bot identity; master/subaccount; environment and DEX; exact coin; direction;
   requested size; submission timestamp; and fencing token. The same record
   must be shared atomically across all three bots.
2. **Authenticated order-specific evidence:** independent read-only exchange
   lookup for the exact account, order ID, coin, side, size, and terminal
   status. A caller-supplied JSON blob or local SDK return is not proof.
3. **Complete fills and historical coverage:** verify trade IDs, timestamps,
   partial fills, cumulative size, overlapping windows, pagination,
   retention limits, and separately archived records where necessary.
   An empty response or a recent-only window does not prove no execution.
4. **Account-wide reconciliation:** inspect open orders, positions, concurrent
   bot orders, and other fills under the correct master/subaccount. Do not
   attribute a net position to a particular bot by matching its direction.
5. **Atomic coordinator state transition:** any future release must validate
   the same current intent and fencing token in a durable transaction, with
   stale-worker protection. A Gist update is not an atomic cross-bot claim.
6. **Independent review and explicit deployment authorization:** test with
   disposable state and fake exchange fixtures; review SQL grants, retries,
   crash recovery, and protective closes before any separately approved
   live integration.

## Must remain blocked

- Timeout after possible submission, lost response, crash, or unknown status.
- `filled` from the original parser without validated independent evidence.
- Partial or contradictory fills, missing order ID, wrong account/coin/side.
- Missing or truncated history, saturated API pages, unverified retention.
- Flat exchange position, absent open order, or unverified ownership claim.
- Coordinator unavailable, conflicting reservations, stale fencing token.
- A fake approval or any `review_only` result from offline test modules.

## Scope and next decision

The offline modules deliberately return `hold`, `review_only`, or
`parsed_untrusted`; none is permission to trade or release a claim.
Before designing a live reconciliation implementation, separately review the
real read-only data access plan, authentication boundaries, account mapping,
durable shared coordinator, and a rollback plan. No production credentials,
network requests, Supabase mutations, merges, or trading actions are
authorized by PR #40.
