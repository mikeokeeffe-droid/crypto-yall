"""CI-only bridge from signed OIDC TEST FIXTURE to disposable review journal.

This module deliberately has no exchange sender, real issuer key discovery,
remote listener, runtime authenticator or trading permission. Its private keys,
clock, database password, account and policy are all injected TEST fixtures.
Never deploy or import this as a production authentication boundary.
"""
from dataclasses import dataclass
import json
import os

from sender_review.offline_oidc_identity_fixture import (
    verify_fixture_oidc_identity_offline,
)
from sender_review.request_contract import inspect_sender_entry_request_offline


@dataclass(frozen=True)
class FixtureBridgeResult:
    state: str = "hold"
    reason: str = "not authenticated runtime"
    fixture_bot: str | None = None
    fixture_signature_checked: bool = False
    journal_recorded: bool = False
    assigned_fence: int | None = None
    runtime_identity_authenticated: bool = False
    request_authorized: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False


def inspect_and_record_signed_fixture_offline(
    *, token, body, policy, fixture_keys, fixture_now_seconds,
    fixed_test_account, db_password,
):
    """Atomic durable fixture JTI consumption and review-only intent record.

    All caller-controlled bot/account claims are ignored. A signed fixture
    workflow_ref identifies the test bot; a fixed test account is server-side
    harness configuration. SQL writes are limited to a named disposable DB.
    A denied journal reservation rolls back the JTI receipt transaction.
    """
    hold = FixtureBridgeResult()
    if (
        os.environ.get("SENDER_REVIEW_DISPOSABLE_CI") != "1"
        or os.environ.get("PGDATABASE") != "sender_review_test"
        or os.environ.get("PGHOST") != "127.0.0.1"
        or type(fixed_test_account) is not str
        or len(fixed_test_account) != 42
        or not fixed_test_account.startswith("0x")
        or any(c not in "0123456789abcdef" for c in fixed_test_account[2:])
        or type(db_password) is not str or not db_password
    ):
        return hold

    identity = verify_fixture_oidc_identity_offline(
        token=token, policy=policy, trusted_fixture_keys=fixture_keys,
        fixture_now_seconds=fixture_now_seconds,
    )
    if (
        identity.state != "verified_fixture_only"
        or not identity.fixture_signature_checked
        or identity.fixture_bot not in ("daily", "intraday", "aggressive")
        or not identity.fixture_jti
    ):
        return hold

    parsed = inspect_sender_entry_request_offline(body=body)
    if parsed.state != "review_only":
        return FixtureBridgeResult(
            reason="invalid or non-entry request", fixture_bot=identity.fixture_bot,
            fixture_signature_checked=True,
        )
    request = json.loads(body)
    try:
        import psycopg
        # Explicit loopback test service ONLY; no configurable DB URL/host.
        with psycopg.connect(
            host="127.0.0.1", port=5432, dbname="sender_review_test",
            user="postgres", password=db_password, connect_timeout=3,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO sender_review_ci.fixture_identity_receipts "
                    "(environment,account,jti,bot,request_nonce) "
                    "VALUES ('testnet',%s,%s,%s,%s) "
                    "ON CONFLICT DO NOTHING RETURNING jti",
                    (fixed_test_account, identity.fixture_jti,
                     identity.fixture_bot, request["request_nonce"]),
                )
                if cur.fetchone() is None:
                    return FixtureBridgeResult(
                        reason="fixture-token-or-nonce-replayed",
                        fixture_bot=identity.fixture_bot,
                        fixture_signature_checked=True,
                    )
                cur.execute(
                    "SELECT recorded,assigned_fence,reason "
                    "FROM sender_review_ci.record_review_only("
                    "%s,%s,%s,%s,%s,%s,%s,%s)",
                    (fixed_test_account, identity.fixture_bot,
                     request["coin"], request["action"], request["side"],
                     request["rounded_size"], request["requested_leverage"],
                     request["request_nonce"]),
                )
                recorded, fence, reason = cur.fetchone()
                if not recorded:
                    # The receipt must not survive a denied journal record.
                    conn.rollback()
                    return FixtureBridgeResult(
                        reason="journal-denied:" + str(reason),
                        fixture_bot=identity.fixture_bot,
                        fixture_signature_checked=True,
                    )
        return FixtureBridgeResult(
            state="persisted_fixture_review_only_HOLD",
            reason="test-only signed identity and journal recorded; "
                   "NO runtime auth or permission to submit",
            fixture_bot=identity.fixture_bot,
            fixture_signature_checked=True,
            journal_recorded=True,
            assigned_fence=fence,
        )
    except (ImportError, Exception):
        # A database or transaction error is always a HOLD, never an approval.
        return FixtureBridgeResult(
            reason="disposable-journal-error",
            fixture_bot=identity.fixture_bot,
            fixture_signature_checked=True,
        )
