"""GitHub Actions runner OIDC token handoff prototype; NO TRADING.

This helper is not connected to any existing workflow or protected sender.
No signer, exchange, order transport or database is imported. The reviewed draft never fetches a token, including when passed True.
Retrieval and server authentication require a separate reviewed change.
NEVER log or persist JWTs.
"""
from dataclasses import dataclass, field
import re
import urllib.parse

AUDIENCE = "urn:crypto-yall:protected-sender:testnet:review"
RUNNER_OIDC_HOST = "pipelines.actions.githubusercontent.com"
_JWT = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\Z", re.ASCII)


@dataclass(frozen=True)
class RunnerOidcHandoffReview:
    state: str = "hold"
    reason: str = "runner token retrieval not approved"
    # Secret only for future protected sender handoff, never print or log.
    bearer_token: str | None = field(default=None, repr=False, compare=False)
    candidate_token_present: bool = False
    server_identity_authenticated: bool = False
    sender_request_authorized: bool = False
    database_claim_recorded: bool = False
    exchange_position_verified: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    signing_enabled: bool = False


def _reject_duplicate_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _token_endpoint_url(url):
    if type(url) is not str or len(url) > 3072:
        return None
    try:
        parts = urllib.parse.urlsplit(url)
        if (parts.scheme != "https" or parts.hostname != RUNNER_OIDC_HOST
                or parts.port not in (None, 443)
                or parts.username is not None or parts.password is not None
                or parts.fragment or "\\" in parts.path
                or not parts.path.startswith("/")
                or not parts.path.endswith("/idtoken")
                or "/_apis/" not in parts.path
                or parts.path.startswith("//")):
            return None
        queries = urllib.parse.parse_qsl(parts.query, keep_blank_values=True,
                                         strict_parsing=True, max_num_fields=16)
        if any(k.lower() == "audience" for k, _ in queries):
            return None
        query = urllib.parse.urlencode(queries + [("audience", AUDIENCE)])
        return urllib.parse.urlunsplit(
            ("https", RUNNER_OIDC_HOST, parts.path, query, "")
        )
    except (ValueError, UnicodeError):
        return None


def request_runner_oidc_token_review(
    *, explicitly_enabled=False, actions_request_url=None,
    actions_request_token=None,
):
    """Always HOLD: the runner's token retrieval is not authorized.

    A caller-supplied URL/token or Boolean cannot activate outbound network
    or authenticate a GitHub identity. Use _token_endpoint_url only for
    pure offline URL-validation tests. Future remote OIDC handling requires
    separately reviewed transport and real security approval.
    """
    return RunnerOidcHandoffReview()
