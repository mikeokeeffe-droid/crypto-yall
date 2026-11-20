# PR #40 — bot identity trust boundary (offline design only)

Status: **DRAFT / NO-GO**. This document does not authenticate any live bot, enable exchange orders, or alter original executors.

## Existing evidence and limitation

The disposable SQLite journal records a caller-supplied `bot` string (`daily`, `intraday`, `aggressive`). Its account-scoped uniqueness and restart tests demonstrate claim retention, **not authentication**. A process able to invoke `reserve(bot="intraday", ...)` can impersonate Intraday. Neither a matching token/fence nor a matching account/coin proves which bot initiated the request. A CLOID is a correlation identifier, not a bot credential.

## Required boundary before any live integration

1. A single coordinated sender must receive a request through an authenticated, authorized channel. The bot identity must come from independently validated workload identity, **never** from a request field or a GitHub Actions environment variable supplied by the requesting job.
2. Assign a separate identity to Daily, Intraday and Aggressive, with per-bot permissions and rotation/revocation. Bind verified identity, environment, account and intended scope to the durable claim and audit record in one transaction.
3. Reject requests when verified identity is absent, expired, revoked, mismatched, or when the same credential is presented from an unauthorized workload. Do not fall back to caller-supplied bot names.
4. Authenticate and authorize any claim lookup, retry, reconciliation or close request separately. A valid token, CLOID or fence must **not** grant authority to close a position or transfer claim ownership.
5. The sender must independently reconcile exchange orders, fills and current position before any bounded close; ambiguous outcomes stay held for review. Prevent direct executor bypass of the coordinated sender.
6. Preserve a strict separation of testnet/mainnet identities and account allowlists. No shared secret or signing authority in CI offline tests.

## Required negative tests

- Daily supplies `bot="intraday"`: reject without Intraday's independently verified workload identity.
- Aggressive replays a Daily token/CLOID/fence: reject, even if coin and account match.
- Correct identity, wrong account or environment: reject.
- Expired/revoked identity, missing verifier, or unavailable identity provider: hold; no dispatch.
- Valid entry identity used to authorize a close owned by another bot: reject pending independently verified provenance.
- Restart or concurrent callers cannot bypass identity verification by reading the journal directly.

## Explicit non-claims

Current `offline_sender_restart_journal.py` and `offline_journaled_fake_dispatch.py` do not enforce this trust boundary. Their passing tests are **not** evidence of independent bot authentication. No live deployment approval should be inferred from this document or the CI results.
