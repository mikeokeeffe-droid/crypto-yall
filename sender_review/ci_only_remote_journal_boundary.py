"""OFFLINE CI fixture chain: HTTP envelope -> fake OIDC -> disposable HOLD.

This is NOT an HTTP listener, trusted GitHub OIDC authenticator, deployment
endpoint, testnet collector, order router or signer. The RSA key and clock are
test supplied, and the only possible persistence is in the explicitly guarded
disposable sender_review_test database. Never import in live bot workflows.
"""
from dataclasses import dataclass
import hashlib

from sender_review.remote_request_boundary_offline import (
    OFFLINE_REQUEST_POLICY, inspect_signed_remote_request_offline,
)
from sender_review.ci_only_identity_bridge import (
    inspect_and_record_signed_fixture_offline,
)


@dataclass(frozen=True)
class RemoteJournalFixtureResult:
    state: str = "hold"
    reason: str = "no trusted runtime identity, transport or signing authority"
    fixture_bot: str | None = None
    request_sha256: str | None = None
    journal_recorded: bool = False
    # These deliberately remain false for ALL possible fixture outcomes.
    runtime_identity_authenticated: bool = False
    tls_peer_authenticated: bool = False
    request_authorized: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    leverage_authorized: bool = False
    signing_enabled: bool = False


def review_remote_fixture_to_disposable_journal_offline(
    *, method, path, headers, body, trusted_fixture_keys,
    fixture_now_seconds, fixed_test_account, db_password,
):
    """One-way fake request inspection; no executable order authority.

    The exact envelope is validated before attempting a CI-only database
    write. The same signed fake token and exact body bytes are passed to the
    existing transactional receipt/journal/evidence bridge. If any stage
    fails, return HOLD. No caller-supplied bot or scope can grant authority.
    """
    hold = RemoteJournalFixtureResult()
    inspection = inspect_signed_remote_request_offline(
        method=method, path=path, headers=headers, body=body,
        trusted_fixture_keys=trusted_fixture_keys,
        fixture_now_seconds=fixture_now_seconds,
    )
    if inspection.state != "signed_fixture_review_only":
        return hold
    # Only two recognized, unique headers can pass the preceding boundary.
    auth_values = [
        value for name, value in headers
        if name.lower() == "authorization"
    ]
    if len(auth_values) != 1 or not auth_values[0].startswith("Bearer "):
        return hold
    token = auth_values[0][7:]
    result = inspect_and_record_signed_fixture_offline(
        token=token, body=body, policy=OFFLINE_REQUEST_POLICY,
        fixture_keys=trusted_fixture_keys,
        fixture_now_seconds=fixture_now_seconds,
        fixed_test_account=fixed_test_account,
        db_password=db_password,
    )
    if (result.state != "persisted_fixture_review_only_HOLD"
            or not result.journal_recorded
            or result.fixture_bot != inspection.fixture_bot):
        return hold
    return RemoteJournalFixtureResult(
        state="persisted_remote_fixture_review_only_HOLD",
        reason="fake HTTP/identity evidence and review journal only; no trade",
        fixture_bot=inspection.fixture_bot,
        request_sha256=hashlib.sha256(body).hexdigest(),
        journal_recorded=True,
    )
