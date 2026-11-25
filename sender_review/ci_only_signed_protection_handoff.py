"""SIGNED FAKE HTTP -> durable synthetic protection HOLD, CI ONLY.

This module is NOT a deployable authentication service, remote listener,
protection controller, order sender or live database adapter. It accepts only
a signed TEST fixture and writes only to localhost sender_review_test in the
disposable GitHub CI environment. No real GitHub OIDC key provenance, issuer
transport, real exchange outcome, position ownership or signer exists.

Journal/evidence recording happens first. If a process dies after that
commit but before the synthetic protection hold commits, the journal's
account/coin fence remains held. A separately implemented incident/recovery
review is required: we never report real protective coverage or release
the account/coin lock.
"""
from dataclasses import dataclass
import hashlib
import json
import os

from sender_review.ci_only_remote_journal_boundary import (
    review_remote_fixture_to_disposable_journal_offline,
)


@dataclass(frozen=True)
class SignedProtectionFixtureHandoff:
    state: str = "HOLD"
    reason: str = "not runtime authenticated"
    fixture_bot: str | None = None
    journal_recorded: bool = False
    simulated_protection_hold_recorded: bool = False
    persisted_scope_fence: int | None = None
    runtime_identity_authenticated: bool = False
    real_exchange_outcome_verified: bool = False
    position_ownership_verified: bool = False
    protective_exit_confirmed: bool = False
    lock_released: bool = False
    retry_authorized: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    signing_enabled: bool = False


def record_signed_protection_fixture_offline(
    *, method, path, headers, body, trusted_fixture_keys,
    fixture_now_seconds, fixed_test_account, db_password, outcome_fixture,
):
    """Persist fake signed entry evidence then an inseparable synthetic HOLD.

    A fixture may assert 'claimed_closed', but this cannot unlock anything.
    A second identical signed request is replay and cannot create a hold.
    A failed second stage leaves the first stage fenced and HOLD.
    """
    default = SignedProtectionFixtureHandoff()
    if (os.environ.get("SENDER_REVIEW_DISPOSABLE_CI") != "1"
            or os.environ.get("PGDATABASE") != "sender_review_test"
            or os.environ.get("PGHOST") != "127.0.0.1"
            or type(outcome_fixture) is not str
            or outcome_fixture not in (
                "pending_exit", "unknown_ack", "partial_fill",
                "claimed_closed",
            )
            or type(body) is not bytes
            or type(fixed_test_account) is not str
            or fixed_test_account != "0x" + "1" * 40
            or type(db_password) is not str or not db_password):
        return default
    result = review_remote_fixture_to_disposable_journal_offline(
        method=method, path=path, headers=headers, body=body,
        trusted_fixture_keys=trusted_fixture_keys,
        fixture_now_seconds=fixture_now_seconds,
        fixed_test_account=fixed_test_account, db_password=db_password,
    )
    if (result.state != "persisted_remote_fixture_review_only_HOLD"
            or result.journal_recorded is not True
            or result.fixture_bot not in ("daily", "intraday", "aggressive")):
        return default
    partial = SignedProtectionFixtureHandoff(
        reason="signed test entry recorded; synthetic protection HOLD unverified",
        fixture_bot=result.fixture_bot, journal_recorded=True,
    )
    # These exact bytes already passed the upstream canonical contract.
    # DO NOT derive scope, bot or trust from request-supplied arbitrary
    # headers: the evidence lookup below uses the fixture-signed bot.
    try:
        doc = json.loads(body)
        if type(doc) is not dict:
            return partial
        token_values = [
            val[7:] for name, val in headers
            if name.lower() == "authorization" and val.startswith("Bearer ")
        ]
        if len(token_values) != 1:
            return partial
        token_hash = hashlib.sha256(token_values[0].encode("ascii")).hexdigest()
        body_hash = hashlib.sha256(body).hexdigest()

        import psycopg
        with psycopg.connect(
            host="127.0.0.1", port=5432, dbname="sender_review_test",
            user="postgres", password=db_password, connect_timeout=3,
        ) as db:
            # Signed TEST fixture JTI, body hash, token hash, account,
            # bot, nonce, side and current fence all must cross-match.
            # This is a CI proof only. There are no runtime scoped DB roles.
            row = db.execute(
                "SELECT i.fence FROM sender_review_ci.review_intents AS i "
                "JOIN sender_review_ci.fixture_request_evidence AS e "
                "ON e.intent_id=i.id "
                "JOIN sender_review_ci.scope_fences AS s "
                "ON s.environment=i.environment AND s.account=i.account "
                "AND s.dex=i.dex AND s.coin=i.coin "
                "WHERE i.environment='testnet' AND i.account=%s "
                "AND i.coin=%s AND i.dex='' AND i.bot=%s AND i.side=%s "
                "AND i.request_nonce=%s AND e.body_sha256=%s "
                "AND e.token_sha256=%s AND e.bot=i.bot "
                "AND e.environment=i.environment AND e.account=i.account "
                "AND e.request_nonce=i.request_nonce "
                "AND s.active_nonce=i.request_nonce AND s.fence=i.fence "
                "FOR UPDATE OF i,s",
                (fixed_test_account, doc["coin"], result.fixture_bot,
                 doc["side"], doc["request_nonce"], body_hash, token_hash),
            ).fetchone()
            if row is None:
                return partial
            fence = row[0]
            held = db.execute(
                "SELECT recorded,reason FROM "
                "sender_review_ci.record_ci_protection_reentry_hold("
                "%s,%s,%s,%s,%s,%s,%s)",
                (fixed_test_account, result.fixture_bot, doc["coin"],
                 doc["side"], doc["request_nonce"], fence, outcome_fixture),
            ).fetchone()
            if held != (True, "durable-review-only-protection-HOLD"):
                return partial
        return SignedProtectionFixtureHandoff(
            state="PERSISTED_FAKE_PROTECTION_HOLD_NO_GO",
            reason="signed synthetic request and permanent review-only HOLD; "
                   "no remote auth, exchange protection or order authority",
            fixture_bot=result.fixture_bot, journal_recorded=True,
            simulated_protection_hold_recorded=True,
            persisted_scope_fence=fence,
        )
    except Exception:
        # A DB outage after the initial commit must never claim the second
        # stage succeeded. The original account/coin fence remains held.
        return partial
