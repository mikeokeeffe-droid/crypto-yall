# Three-bot signer-free intent interfaces — offline review, NO-GO

**15 November 2026. Design only; not a deployed or trading-capable API.**

The new `sender_review/proposed_intent_interfaces_offline.py` is a pure
parser of *untrusted fixture requests*. A valid request is
`parsed_review_only_HOLD`, never an authorization.

| Request family | Proposed request data | Trust boundary / unresolved checks |
|---|---|---|
| Daily/Intraday/Aggressive entry | Version, open-long/short, side, uppercase coin, positive rounded decimal size, 1–5 proposed leverage, nonce | Verify real OIDC workflow identity; server-pin account/network/DEX and limits; DB fence; trusted market precision, position/risk and duplicate-order checks |
| Aggressive pyramid | Entry fields plus existing parent position reference | Server independently verifies authenticated Aggressive identity and positive attributed position/fill, side, size allocation and account-wide exposure; reject conflicting or stale state |
| All three protective closes | Explicit positive close size, observed size, position reference, exit reason (signal, profit floor, trailing, USD loss cap), **requested** reduce-only=true | Caller observations and owner claims are not trusted; server must independently query position/fills and current precision, verify attributable size, select actual reduce-only semantics and fence close; never allow unbounded `market_close(coin)` |
| All three leverage requests | Separate leverage proposal plus parent position reference | Server must independently enforce current account/market caps and position/fence safety before applying any setting |

The original S1 entry-only contract is unchanged: it still rejects close,
pyramid and leverage requests. The proposed review interfaces are not
connected to the PostgreSQL journal or any remote sender, signer, wallet,
Hyperliquid SDK, GitHub Actions executor or network. It is unsafe to treat a
syntactically valid close request as evidence that a position exists or belongs
to that bot.

## Required future implementation gates

1. An independently verified authenticated service, using real GitHub-issued
   identity and a trusted clock/JWKS/HTTPS origin, must derive identity rather
   than accept caller-selected bot/account.
2. A single writer must own *all* order, close and leverage changes; remove
   signing secrets and egress from **all five** current execution paths
   (Daily ×1, Intraday ×2, Aggressive ×2) atomically with an approved rollback.
3. Entry requests need server-side size/market notional and risk decisions.
   Pyramid requests need parent attribution and one account-wide position lock.
4. Protective exits need independently verified ownership, bounded explicit
   size, exchange-supported reduce-only enforcement, partial fill/ACK handling,
   and an emergency policy that does not silently leave positions unprotected.
5. Do not change production/CI bot scheduling, wallet secrets, Supabase,
   exchange endpoints, or trading permissions on the strength of these tests.
6. Obtain independent security and trading-risk signoff on exact runtime
   version, host isolation and testnet-only approval before any remote testing.

**Status: design review only; NO-GO for testnet and live orders.**
