"""Offline signed GitHub Actions OIDC identity POLICY prototype.

This is not a deployable authenticator: keys and clock come from the TEST
HARNESS, not a independently trusted issuer/JWKS service and runtime clock.
Never use this fixture result as live workload authentication, a DB permission,
nonce reservation or authorisation to trade. Future server must pin real
GitHub issuer JWKS by trustworthy transport/rotation and securely obtain time,
then independently enforce the same policy before touching the journal.

Signer here means OIDC RSA *verifier*, not a trading wallet signer. This module
has no exchange SDK, network transport, accounts, secrets, or database code.
"""
import base64
from dataclasses import dataclass
import json
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

_ISSUER = "https://token.actions.githubusercontent.com"
_B64 = re.compile(r"[A-Za-z0-9_-]+\Z", re.ASCII)
_JTI = re.compile(r"[A-Za-z0-9_-]{6,128}\Z", re.ASCII)
_DIGITS = re.compile(r"[1-9][0-9]{0,19}\Z", re.ASCII)
_SHA = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)
_BOTS = frozenset(("daily", "intraday", "aggressive"))


@dataclass(frozen=True)
class OfflineOidcTrustPolicy:
    """Explicit test policy; NOT discovered from untrusted JWT claims."""
    repository: str
    repository_id: str
    audience: str
    ref: str
    subject: str
    workflow_bot_refs: tuple[tuple[str, str], ...]
    # Repositories created on/after GitHub's 2026-07-15 rollout require
    # immutable owner/repository IDs in the default OIDC subject.
    repository_owner_id: str | None = None
    immutable_subject: bool = False
    # Optional operator-pinned source and workflow revisions. These are
    # policy inputs, NOT trusted claims just because a token supplies them.
    # Deployment still requires real issuer key and host provenance.
    approved_source_sha: str | None = None
    approved_workflow_sha: str | None = None
    # A paired fixed run/attempt is an OFFLINE fixture expectation,
    # NOT proof GitHub authorized that run or that an operator approved it.
    expected_run_id: str | None = None
    expected_run_attempt: str | None = None


@dataclass(frozen=True)
class OfflineOidcIdentityReview:
    state: str = "hold"
    reason: str = "not a trusted runtime identity"
    fixture_signature_checked: bool = False
    fixture_bot: str | None = None
    fixture_jti: str | None = None
    runtime_identity_authenticated: bool = False
    nonce_reserved: bool = False
    account_scope_verified: bool = False
    request_authorized: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False


def _unique_pairs(items):
    obj = {}
    for key, value in items:
        if key in obj:
            raise ValueError("duplicate key")
        obj[key] = value
    return obj


def _reject_constant(_):
    raise ValueError("non-finite value")


def _part(segment, limit):
    if (type(segment) is not str or len(segment) > limit
            or _B64.fullmatch(segment) is None):
        raise ValueError("invalid base64url segment")
    raw = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    if base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != segment:
        raise ValueError("non-canonical base64url encoding")
    return raw


def verify_fixture_oidc_identity_offline(
    *, token, policy, trusted_fixture_keys, fixture_now_seconds,
):
    """Verify signed fixture and derive 1 bot; result remains NON-AUTHORITY.

    The only source of bot identity is a signed workflow_ref bound to one
    trusted policy entry. The JWT cannot supply a trusted key or new bot.
    Caller-controlled keys and fixture clock make the result unsuitable
    for real service authentication.
    """
    hold = OfflineOidcIdentityReview()
    if (type(token) is not str or not 0 < len(token) <= 16000
            or type(policy) is not OfflineOidcTrustPolicy
            or type(trusted_fixture_keys) is not dict
            or type(fixture_now_seconds) is not int
            or fixture_now_seconds <= 0
            or type(policy.repository) is not str
            or not policy.repository
            or type(policy.repository_id) is not str
            or _DIGITS.fullmatch(policy.repository_id) is None
            or type(policy.audience) is not str or not policy.audience
            or type(policy.ref) is not str
            or not policy.ref.startswith("refs/heads/")
            or type(policy.subject) is not str
            or type(policy.immutable_subject) is not bool
            or (policy.immutable_subject and (
                type(policy.repository_owner_id) is not str
                or _DIGITS.fullmatch(policy.repository_owner_id) is None
            ))
            or (not policy.immutable_subject and
                policy.repository_owner_id is not None)
            or policy.repository.count("/") != 1
            or not all(policy.repository.split("/"))
            or policy.subject != (
                ("repo:" + policy.repository.split("/")[0] + "@" +
                 policy.repository_owner_id + "/" +
                 policy.repository.split("/")[1] + "@" +
                 policy.repository_id + ":ref:" + policy.ref)
                if policy.immutable_subject else
                ("repo:" + policy.repository + ":ref:" + policy.ref)
            )
            or (policy.approved_source_sha is not None
                and (type(policy.approved_source_sha) is not str
                     or _SHA.fullmatch(policy.approved_source_sha) is None))
            or (policy.approved_workflow_sha is not None
                and (type(policy.approved_workflow_sha) is not str
                     or _SHA.fullmatch(policy.approved_workflow_sha) is None))
            or ((policy.expected_run_id is None)
                != (policy.expected_run_attempt is None))
            or (policy.expected_run_id is not None
                and (type(policy.expected_run_id) is not str
                     or _DIGITS.fullmatch(policy.expected_run_id) is None))
            or (policy.expected_run_attempt is not None
                and (type(policy.expected_run_attempt) is not str
                     or _DIGITS.fullmatch(policy.expected_run_attempt) is None))
            or type(policy.workflow_bot_refs) is not tuple
            or len(policy.workflow_bot_refs) != 3):
        return hold
    known_refs = {}
    try:
        for item in policy.workflow_bot_refs:
            if (type(item) is not tuple or len(item) != 2
                    or type(item[0]) is not str or not item[0].startswith(
                        policy.repository + "/.github/workflows/"
                    )
                    or not item[0].endswith("@" + policy.ref)
                    or type(item[1]) is not str or item[1] not in _BOTS
                    or item[0] in known_refs):
                return hold
            known_refs[item[0]] = item[1]
        if set(known_refs.values()) != _BOTS:
            return hold
        parts = token.split(".")
        if len(parts) != 3:
            return hold
        header = json.loads(
            _part(parts[0], 1400).decode("utf-8"),
            object_pairs_hook=_unique_pairs, parse_constant=_reject_constant,
        )
        claims = json.loads(
            _part(parts[1], 10000).decode("utf-8"),
            object_pairs_hook=_unique_pairs, parse_constant=_reject_constant,
        )
        signature = _part(parts[2], 1600)
        if (type(header) is not dict or type(claims) is not dict
                or header.get("alg") != "RS256"
                or header.get("typ") != "JWT"
                or type(header.get("kid")) is not str
                or not 1 <= len(header["kid"]) <= 128):
            return hold
        kid = header["kid"]
        key = trusted_fixture_keys.get(kid)
        if (type(key) is not tuple or len(key) != 2
                or type(key[0]) is not int or type(key[1]) is not int
                or key[0].bit_length() < 2048
                or key[1] != 65537):
            return hold
        pub = rsa.RSAPublicNumbers(key[1], key[0]).public_key()
        pub.verify(
            signature, (parts[0] + "." + parts[1]).encode("ascii"),
            padding.PKCS1v15(), hashes.SHA256(),
        )
        if (claims.get("iss") != _ISSUER
                or claims.get("aud") != policy.audience
                or claims.get("repository") != policy.repository
                or claims.get("repository_id") != policy.repository_id
                or (policy.immutable_subject and
                    claims.get("repository_owner_id") != policy.repository_owner_id)
                or claims.get("ref") != policy.ref
                or claims.get("sub") != policy.subject
                or claims.get("event_name") not in (
                    "schedule", "workflow_dispatch"
                )
                or type(claims.get("workflow_ref")) is not str
                or claims["workflow_ref"] not in known_refs
                or type(claims.get("jti")) is not str
                or _JTI.fullmatch(claims["jti"]) is None
                or type(claims.get("sha")) is not str
                or _SHA.fullmatch(claims["sha"]) is None
                or (policy.approved_source_sha is not None
                    and claims["sha"] != policy.approved_source_sha)
                or (policy.approved_workflow_sha is not None
                    and (type(claims.get("workflow_sha")) is not str
                         or claims["workflow_sha"] != policy.approved_workflow_sha))
                or type(claims.get("run_id")) is not str
                or _DIGITS.fullmatch(claims["run_id"]) is None
                or type(claims.get("run_attempt")) is not str
                or _DIGITS.fullmatch(claims["run_attempt"]) is None
                or (policy.expected_run_id is not None
                    and (claims["run_id"] != policy.expected_run_id
                         or claims["run_attempt"] != policy.expected_run_attempt))
                or any(type(claims.get(t)) is not int
                       for t in ("nbf", "iat", "exp"))):
            return hold
        nbf, iat, exp = (claims[x] for x in ("nbf", "iat", "exp"))
        if (iat > fixture_now_seconds + 30
                or not nbf <= fixture_now_seconds < exp
                or nbf > iat + 30 or exp <= iat
                or exp - iat > 600
                or fixture_now_seconds - iat > 600):
            return hold
        return OfflineOidcIdentityReview(
            state="verified_fixture_only",
            reason="fixture RSA signature and scoped claims valid; real "
                   "issuer key provenance, replay persistence, clock and "
                   "remote transport NOT verified",
            fixture_signature_checked=True,
            fixture_bot=known_refs[claims["workflow_ref"]],
            fixture_jti=claims["jti"],
        )
    except (ValueError, TypeError, KeyError, UnicodeError,
            InvalidSignature, OverflowError):
        return hold
