"""Offline HTTP-envelope + signed GitHub OIDC fixture review for PR #42.

No HTTP server, network, issuer JWKS discovery, TLS termination, DB connection,
trading signer or executable permission. Keys and clock are test-fixture inputs.
An accepted fixture remains NON-AUTHORIZING and cannot submit or close orders.
Future service MUST independently resolve GitHub JWKS over authenticated
transport, bind a real server clock and persistent token replay records, and
obtain a separate security approval before any deployment.
"""
from dataclasses import dataclass
import hashlib

from sender_review.offline_oidc_identity_fixture import (
    OfflineOidcTrustPolicy, verify_fixture_oidc_identity_offline,
)
from sender_review.request_contract import inspect_sender_entry_request_offline

# Exact existing workflow paths on main, audited as of 2026-11-15. The three
# original jobs still have HL_PRIVATE_KEY and are NOT OIDC request-only jobs.
# These refs describe a future proposed cutover; nothing is enabled here.
_REPO = "mikeokeeffe-droid/crypto-yall"
_REF = "refs/heads/main"
_AUDIENCE = "urn:crypto-yall:protected-sender:testnet:review"
_WORKFLOWS = (
    (_REPO + "/.github/workflows/execute-trades.yml@" + _REF, "daily"),
    (_REPO + "/.github/workflows/execute-intraday.yml@" + _REF, "intraday"),
    (_REPO + "/.github/workflows/execute-aggressive.yml@" + _REF, "aggressive"),
)
OFFLINE_REQUEST_POLICY = OfflineOidcTrustPolicy(
    repository=_REPO,
    repository_id="1327094015",
    audience=_AUDIENCE,
    ref=_REF,
    subject="repo:mikeokeeffe-droid@313842984/crypto-yall@1327094015:ref:" + _REF,
    workflow_bot_refs=_WORKFLOWS,
    repository_owner_id="313842984",
    immutable_subject=True,
)
_REQUEST_PATH = "/v1/review-only/entry-intents"


@dataclass(frozen=True)
class RemoteRequestReview:
    state: str = "hold"
    reason: str = "offline request has no server authority"
    fixture_bot: str | None = None
    fixture_signature_checked: bool = False
    request_sha256: str | None = None
    runtime_identity_authenticated: bool = False
    tls_peer_authenticated: bool = False
    replay_consumed: bool = False
    account_scope_verified: bool = False
    request_authorized: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    signing_enabled: bool = False


def inspect_signed_remote_request_offline(
    *, method, path, headers, body, trusted_fixture_keys, fixture_now_seconds,
):
    """Strictly inspect a proposed remote request, but ALWAYS deny authority.

    Headers are a raw list/tuple of name/value pairs so duplicate auth headers
    and mixed-case aliases cannot silently overwrite one another. No trust is
    placed in caller-provided account, network, bot or authorization flags.
    """
    hold = RemoteRequestReview()
    if (method != "POST" or path != _REQUEST_PATH or type(headers) not in
            (list, tuple) or len(headers) != 2 or type(body) is not bytes
            or not 0 < len(body) <= 1024):
        return hold
    normalized = {}
    for item in headers:
        if (type(item) not in (tuple, list) or len(item) != 2
                or type(item[0]) is not str or type(item[1]) is not str
                or len(item[0]) > 80 or len(item[1]) > 16064
                or any(c in item[0] + item[1] for c in "\r\n\0")):
            return hold
        name = item[0].lower()
        if name not in ("authorization", "content-type") or name in normalized:
            return hold
        normalized[name] = item[1]
    if normalized.get("content-type") != "application/json":
        return hold
    auth = normalized.get("authorization", "")
    if not auth.startswith("Bearer ") or auth.count(" ") != 1:
        return hold
    token = auth[7:]
    if not token or len(token) > 16000:
        return hold

    # A valid fixture identity is NOT a trusted runtime identity.
    identity = verify_fixture_oidc_identity_offline(
        token=token,
        policy=OFFLINE_REQUEST_POLICY,
        trusted_fixture_keys=trusted_fixture_keys,
        fixture_now_seconds=fixture_now_seconds,
    )
    if identity.state != "verified_fixture_only":
        return hold
    parsed = inspect_sender_entry_request_offline(body=body)
    if parsed.state != "review_only":
        return RemoteRequestReview(
            reason="signed fixture, invalid request contract",
            fixture_bot=identity.fixture_bot,
            fixture_signature_checked=True,
        )
    return RemoteRequestReview(
        state="signed_fixture_review_only",
        reason="signed fixture and strict request match; NO runtime issuer "
               "key provenance, authenticated HTTPS, replay consumption, "
               "account scope, execution or signing",
        fixture_bot=identity.fixture_bot,
        fixture_signature_checked=True,
        request_sha256=hashlib.sha256(body).hexdigest(),
    )
