"""GitHub Actions runner OIDC token handoff prototype; NO TRADING.

This helper is not connected to any existing workflow or protected sender.
No signer, exchange, order transport or database is imported. A runner may
retrieve a *short-lived token* only when an operator separately enables this
read-only action and the job has id-token: write. Retrieval is NOT server-side
authentication or approval to submit orders. NEVER log or persist JWTs.
"""
from dataclasses import dataclass, field
import json
import re
import ssl
import urllib.parse
import urllib.request

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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


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
    """Opt-in GitHub runner token retrieval; NEVER approves a sender request.

    The URL/token must originate from GitHub runner-provided environment
    variables, not client JSON. This function does not read env directly,
    allowing a future trusted caller to enforce provenance. Tests mock all
    HTTPS calls, and no workflow currently calls this helper.
    """
    denied = RunnerOidcHandoffReview()
    if (explicitly_enabled is not True
            or type(actions_request_token) is not str
            or not 20 <= len(actions_request_token) <= 8192
            or any(x in actions_request_token for x in "\r\n\0")):
        return denied
    url = _token_endpoint_url(actions_request_url)
    if url is None:
        return denied
    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        request = urllib.request.Request(url, method="GET", headers={
            "Authorization": "Bearer " + actions_request_token,
            "Accept": "application/json",
        })
        with opener.open(request, timeout=5) as response:
            if (response.status != 200 or response.geturl() != url
                    or response.headers.get("Content-Type", "").split(";")[0]
                    .strip().lower() != "application/json"):
                return denied
            body = response.read(16385)
        if not 0 < len(body) <= 16384:
            return denied
        result = json.loads(body.decode("utf-8"),
                            object_pairs_hook=_reject_duplicate_json)
        if (type(result) is not dict
                or not set(result) <= {"value", "count"}
                or "value" not in result
                or ("count" in result and result["count"] != 1)):
            return denied
        jwt = result["value"]
        if (type(jwt) is not str or not 100 <= len(jwt) <= 16000
                or _JWT.fullmatch(jwt) is None):
            return denied
        return RunnerOidcHandoffReview(
            state="candidate_runner_token_unverified_HOLD",
            reason="GitHub runner token obtained; remote issuer, claims, "
                   "replay, service authorization and sender unavailable",
            bearer_token=jwt,
            candidate_token_present=True,
        )
    except (OSError, ValueError, TypeError, UnicodeError):
        return denied
