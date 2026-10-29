"""Staging-only WSGI handler for authenticated entry reservation requests.

The app is a callable, not a network server. Server code supplies independent
per-bot signing keys, connection factories, and restricted PostgreSQL LOGINs.
"""
import json
from collections.abc import Mapping

from staging_executor_gateway_contract import BOTS, ENTRY_ACTIONS
from trusted_executor_gateway_staging import (
    EntryClaimDenied,
    stage_entry_claim,
)
from trusted_executor_jwt_staging import ExecutorAuthenticationError
from trusted_executor_postgres_transport_staging import (
    ExecutorDatabaseError,
    ExecutorIdentityMismatch,
    restricted_executor_rpc,
)

ENTRY_CLAIM_PATH = "/staging/entry-claims"
MAX_REQUEST_BYTES = 4096

_REASONS = {
    200: "OK",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    503: "Service Unavailable",
}


def _reject_duplicate_fields(pairs):
    fields = {}
    for key, value in pairs:
        if key in fields:
            raise ValueError("duplicate JSON field")
        fields[key] = value
    return fields


class StagingExecutorEntryApp:
    """An authenticated staging gateway; constructing it opens no listener."""

    def __init__(
        self,
        *,
        signing_keys,
        connection_factories,
        expected_logins,
        issuer,
        audience,
    ):
        for configured in (signing_keys, connection_factories, expected_logins):
            if not isinstance(configured, Mapping) or set(configured) != BOTS:
                raise ValueError("complete per-bot server configuration required")
        if (type(issuer) is not str or not issuer.strip()
                or type(audience) is not str or not audience.strip()):
            raise ValueError("trusted issuer and audience are required")
        keys = tuple(signing_keys.values())
        if (any(type(key) is not bytes or len(key) < 32 for key in keys)
                or len(set(keys)) != len(BOTS)):
            raise ValueError("distinct per-bot signing keys are required")
        logins = tuple(expected_logins.values())
        if (any(type(login) is not str or not login for login in logins)
                or len(set(logins)) != len(BOTS)):
            raise ValueError("distinct per-bot database LOGINs are required")
        if any(not callable(factory) for factory in connection_factories.values()):
            raise ValueError("per-bot database connection factories are required")

        self._signing_keys = dict(signing_keys)
        self._issuer = issuer
        self._audience = audience
        self._rpcs = {
            bot: restricted_executor_rpc(
                connection_factories[bot],
                expected_login=expected_logins[bot],
                expected_bot=bot,
            )
            for bot in BOTS
        }

    def __call__(self, environ, start_response):
        if environ.get("PATH_INFO") != ENTRY_CLAIM_PATH:
            return self._respond(start_response, 404, {"error": "not found"})
        if environ.get("REQUEST_METHOD") != "POST":
            return self._respond(
                start_response, 405, {"error": "method not allowed"},
                extra_headers=(("Allow", "POST"),),
            )

        try:
            request = self._read_request(environ)
        except (
            KeyError, TypeError, ValueError, UnicodeDecodeError, OSError,
            RecursionError,
        ):
            return self._respond(start_response, 400, {"error": "invalid request"})

        bot = request["bot"]
        if bot not in BOTS:
            return self._respond(start_response, 400, {"error": "invalid request"})
        if (type(request["coin"]) is not str or not request["coin"].isascii()
                or not request["coin"].isalnum()
                or request["coin"] != request["coin"].upper()
                or type(request["action"]) is not str):
            return self._respond(start_response, 400, {"error": "invalid request"})
        if request["action"] not in ENTRY_ACTIONS:
            return self._respond(start_response, 403, {"error": "action forbidden"})

        authorization = environ.get("HTTP_AUTHORIZATION")
        if type(authorization) is not str:
            return self._unauthorized(start_response)
        scheme, separator, token = authorization.partition(" ")
        if (not separator or scheme.lower() != "bearer" or not token
                or any(character.isspace() for character in token)):
            return self._unauthorized(start_response)
        try:
            claim = stage_entry_claim(
                jwt_token=token,
                bot=bot,
                coin=request["coin"],
                action=request["action"],
                signing_keys=self._signing_keys,
                issuer=self._issuer,
                audience=self._audience,
                rpc=self._rpcs[bot],
            )
        except ExecutorAuthenticationError:
            return self._unauthorized(start_response)
        except EntryClaimDenied:
            return self._respond(start_response, 409, {"error": "entry claim denied"})
        except (ExecutorDatabaseError, ExecutorIdentityMismatch):
            return self._respond(start_response, 503, {"error": "database unavailable"})
        except PermissionError:
            return self._respond(start_response, 403, {"error": "request forbidden"})

        return self._respond(
            start_response,
            200,
            {
                "reservation_claimed": claim.claimed,
                "intent_claimed": claim.claimed,
            },
        )

    @staticmethod
    def _read_request(environ):
        if environ.get("CONTENT_TYPE", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("JSON content type required")
        length = environ.get("CONTENT_LENGTH")
        if (type(length) is not str or not length or not length.isascii()
                or not length.isdecimal()):
            raise ValueError("content length required")
        size = int(length)
        if not 0 < size <= MAX_REQUEST_BYTES:
            raise ValueError("request size rejected")
        stream = environ.get("wsgi.input")
        if stream is None:
            raise ValueError("request body missing")
        raw_body = stream.read(size)
        if type(raw_body) is not bytes or len(raw_body) != size:
            raise ValueError("incomplete request body")
        payload = json.loads(raw_body.decode("utf-8"), object_pairs_hook=_reject_duplicate_fields)
        if (not isinstance(payload, dict)
                or set(payload) != {"bot", "coin", "action"}
                or any(type(payload[field]) is not str
                       for field in ("bot", "coin", "action"))):
            raise ValueError("invalid request fields")
        return payload

    @classmethod
    def _unauthorized(cls, start_response):
        return cls._respond(
            start_response,
            401,
            {"error": "unauthorized"},
            extra_headers=(("WWW-Authenticate", "Bearer"),),
        )

    @staticmethod
    def _respond(start_response, status, payload, extra_headers=()):
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        headers = [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
        ]
        headers.extend(extra_headers)
        start_response(f"{status} {_REASONS[status]}", headers)
        return [body]


def create_staging_executor_entry_app(**server_configuration):
    """Create the callable handler; never starts an HTTP or public listener."""
    return StagingExecutorEntryApp(**server_configuration)
