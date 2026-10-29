"""Callable-only host/client adapter for the staging executor gateway.

No listener or network transport is created here. Deployments must inject a
reviewed transport that enforces the supplied timeout and private TLS policy.
"""
import base64
import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone

from staging_executor_gateway_contract import BOTS, ENTRY_ACTIONS
from staging_executor_http_gateway import (
    ENTRY_CLAIM_PATH,
    MAX_REQUEST_BYTES,
    create_staging_executor_entry_app,
)

DEFAULT_REQUEST_TIMEOUT_SECONDS = 3.0
DATABASE_CONNECT_TIMEOUT_SECONDS = 3
DATABASE_STATEMENT_TIMEOUT_MS = 3000
DATABASE_LOCK_TIMEOUT_MS = 1000
MAX_RESPONSE_BYTES = 4096
_DISALLOWED_LOGINS = frozenset({
    "postgres", "service_role", "bot_entry_executor_trial", "bot_reconciler",
})

_STARTUP_PRIVILEGE_SQL = """
select
  session_user::text,
  current_user::text,
  r.rolcanlogin,
  r.rolsuper,
  r.rolinherit,
  r.rolcreatedb,
  r.rolcreaterole,
  r.rolreplication,
  r.rolbypassrls,
  pg_catalog.pg_has_role(session_user, 'bot_entry_executor_trial', 'MEMBER'),
  not pg_catalog.has_schema_privilege(current_user, 'public', 'CREATE'),
  pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_reservations', 'SELECT'),
  pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_intents', 'SELECT'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_reservations', 'INSERT'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_reservations', 'UPDATE'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_reservations', 'DELETE'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_reservations', 'TRUNCATE'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_reservations', 'REFERENCES'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_reservations', 'TRIGGER'),
  not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_entry_reservations', 'INSERT'),
  not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_entry_reservations', 'UPDATE'),
  not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_entry_reservations', 'REFERENCES'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_intents', 'INSERT'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_intents', 'UPDATE'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_intents', 'DELETE'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_intents', 'TRUNCATE'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_intents', 'REFERENCES'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_intents', 'TRIGGER'),
  not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_entry_intents', 'INSERT'),
  not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_entry_intents', 'UPDATE'),
  not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_entry_intents', 'REFERENCES'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_executor_identities', 'SELECT'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_executor_identities', 'INSERT'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_executor_identities', 'UPDATE'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_executor_identities', 'DELETE'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_executor_identities', 'TRUNCATE'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_executor_identities', 'REFERENCES'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_executor_identities', 'TRIGGER'),
  not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_entry_executor_identities', 'SELECT'),
  not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_entry_executor_identities', 'INSERT'),
  not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_entry_executor_identities', 'UPDATE'),
  not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_entry_executor_identities', 'REFERENCES'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_position_owners', 'SELECT'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_position_owners', 'INSERT'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_position_owners', 'UPDATE'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_position_owners', 'DELETE'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_position_owners', 'TRUNCATE'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_position_owners', 'REFERENCES'),
  not pg_catalog.has_table_privilege(current_user,
    'public.bot_position_owners', 'TRIGGER'),
  not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_position_owners', 'SELECT'),
  not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_position_owners', 'INSERT'),
  not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_position_owners', 'UPDATE'),
  not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_position_owners', 'REFERENCES'),
  pg_catalog.has_function_privilege(current_user,
    'public.try_reserve_bot_entry(text,text,uuid,integer)', 'EXECUTE'),
  pg_catalog.has_function_privilege(current_user,
    'public.claim_bot_entry_intent(text,text,uuid)', 'EXECUTE'),
  pg_catalog.has_function_privilege(current_user,
    'public.release_bot_entry(text,text,uuid)', 'EXECUTE'),
  not pg_catalog.has_function_privilege(current_user,
    'public.resolve_bot_entry_intent(text,text,uuid)', 'EXECUTE'),
  not pg_catalog.has_function_privilege(current_user,
    'public.record_bot_position_owner(text,text,uuid,text,boolean)', 'EXECUTE'),
  not pg_catalog.has_function_privilege(current_user,
    'public.mark_bot_position_closed(text,text,uuid,boolean,boolean)', 'EXECUTE'),
  not pg_catalog.has_function_privilege(current_user,
    'public.release_closed_bot_position(text,text,uuid,boolean,boolean)', 'EXECUTE'),
  not exists (
    select 1 from pg_catalog.pg_roles inherited
    where inherited.rolname not in (session_user::text, 'bot_entry_executor_trial')
      and pg_catalog.pg_has_role(session_user, inherited.oid, 'MEMBER')
  ),
  not exists (
    select 1
    from pg_catalog.pg_proc p
    join pg_catalog.pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and pg_catalog.has_function_privilege(current_user, p.oid, 'EXECUTE')
      and p.oid not in (
        pg_catalog.to_regprocedure(
          'public.try_reserve_bot_entry(text,text,uuid,integer)'),
        pg_catalog.to_regprocedure(
          'public.claim_bot_entry_intent(text,text,uuid)'),
        pg_catalog.to_regprocedure(
          'public.release_bot_entry(text,text,uuid)')
      )
  )
from pg_catalog.pg_roles r
where r.rolname = session_user
"""


class GatewayStartupError(RuntimeError):
    """Startup checks failed; the staging route must not be mounted."""


class GatewayClientError(RuntimeError):
    """The authenticated staging gateway request did not complete safely."""


def _validate_bot_mapping(value, label):
    if not isinstance(value, Mapping) or set(value) != BOTS:
        raise GatewayStartupError(f"complete per-bot {label} configuration required")


def _resolve_secret(provider, reference):
    try:
        if callable(provider):
            value = provider(reference)
        else:
            value = provider.get_secret(reference)
    except Exception as error:
        raise GatewayStartupError("required staging secret is unavailable") from error
    if type(value) not in (str, bytes) or not value:
        raise GatewayStartupError("required staging secret is unavailable")
    return value


def _encode_segment(value):
    return base64.urlsafe_b64encode(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).rstrip(b"=").decode("ascii")


def create_staging_executor_token(*, bot, signing_key, issuer, audience,
                                  lifetime_seconds=60, now=None):
    """Create a short-lived bot-scoped staging token for trusted callers."""
    if (type(bot) is not str or bot not in BOTS
            or type(signing_key) is not bytes or len(signing_key) < 32
            or type(issuer) is not str or not issuer.strip()
            or type(audience) is not str or not audience.strip()
            or type(lifetime_seconds) is not int
            or not 1 <= lifetime_seconds <= 300):
        raise ValueError("valid staging token configuration required")
    issued_at = int(time.time()) if now is None else now
    if type(issued_at) is not int:
        raise ValueError("valid token clock required")
    header = _encode_segment({"alg": "HS256", "typ": "JWT"})
    payload = _encode_segment({
        "aud": audience,
        "exp": issued_at + lifetime_seconds,
        "iat": issued_at,
        "iss": issuer,
        "nbf": issued_at,
        "scope": "executor:entry",
        "sub": "executor:" + bot,
    })
    message = header + "." + payload
    signature = hmac.new(
        signing_key, message.encode("ascii"), hashlib.sha256
    ).digest()
    return message + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")


def _check_login_permissions(factory, expected_login, expected_bot):
    try:
        with factory() as connection:
            postgres_connection = getattr(connection, "pgconn", None)
            if (postgres_connection is None
                    or getattr(postgres_connection, "ssl_in_use", False) is not True):
                raise GatewayStartupError(
                    f"database TLS is not active for {expected_bot}"
                )
            with connection.transaction():
                row = connection.execute(_STARTUP_PRIVILEGE_SQL).fetchone()
                if row is None:
                    raise GatewayStartupError("database LOGIN is unavailable")
                (
                    session_user, current_user, can_login, is_superuser,
                    inherits, createdb, createrole, replication, bypassrls,
                    trial_member, no_public_create, reservation_select,
                    intent_select, *checks,
                ) = row
                if (session_user != expected_login
                        or current_user != expected_login
                        or not can_login or is_superuser or not inherits
                        or createdb or createrole or replication or bypassrls
                        or not trial_member or not no_public_create
                        or not reservation_select or not intent_select
                        or not all(checks)):
                    raise GatewayStartupError(
                        f"database identity or effective grants rejected for {expected_bot}"
                    )

                probe_coin = "PR38" + uuid.uuid4().hex.upper()
                token = str(uuid.uuid4())
                connection.execute("savepoint startup_identity_probe")
                own_reservation = connection.execute(
                    "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
                    (probe_coin, expected_bot, token, 30),
                ).fetchone()[0]
                own_intent = connection.execute(
                    "select public.claim_bot_entry_intent(%s,%s,%s)",
                    (probe_coin, expected_bot, token),
                ).fetchone()[0]
                if own_reservation is not True or own_intent is not True:
                    raise GatewayStartupError(
                        f"database identity mapping rejected for {expected_bot}"
                    )

                other_bot = next(bot for bot in BOTS if bot != expected_bot)
                connection.execute("savepoint cross_bot_identity_probe")
                try:
                    connection.execute(
                        "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
                        (probe_coin + "X", other_bot, str(uuid.uuid4()), 30),
                    )
                except Exception as error:
                    if getattr(error, "sqlstate", None) != "42501":
                        raise GatewayStartupError(
                            "cross-bot database identity check failed"
                        ) from error
                    connection.execute("rollback to savepoint cross_bot_identity_probe")
                    connection.execute("release savepoint cross_bot_identity_probe")
                else:
                    raise GatewayStartupError(
                        "database accepted cross-bot identity impersonation"
                    )
                connection.execute("rollback to savepoint startup_identity_probe")
                connection.execute("release savepoint startup_identity_probe")
    except GatewayStartupError:
        raise
    except Exception as error:
        raise GatewayStartupError(
            f"database startup verification failed for {expected_bot}"
        ) from error


class _AuditedWSGIApp:
    def __init__(self, app, audit_sink):
        self._app = app
        self._audit_sink = audit_sink

    def __call__(self, environ, start_response):
        request_id = str(uuid.uuid4())
        environ["staging.audit_request_id"] = request_id
        status_holder = {}

        def audited_start_response(status, headers, exc_info=None):
            try:
                status_code = int(status.split(" ", 1)[0])
                requested_bot = environ.get("staging.requested_bot")
                requested_action = environ.get("staging.requested_action")
                event = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "request_id": request_id,
                    "status": status_code,
                    "bot": requested_bot if requested_bot in BOTS else None,
                    "action": (
                        requested_action
                        if requested_action in ENTRY_ACTIONS else None
                    ),
                    "outcome": (
                        "claimed" if status_code == 200
                        else "denied" if status_code < 500
                        else "unavailable"
                    ),
                }
                self._audit_sink(event)
            except Exception as error:
                raise GatewayClientError("staging audit sink failed") from error
            status_holder["status"] = status
            if exc_info is None:
                return start_response(status, headers)
            return start_response(status, headers, exc_info)

        try:
            response = self._app(environ, audited_start_response)
        except Exception:
            if "status" not in status_holder:
                self._audit_sink({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "request_id": request_id,
                    "status": 500,
                    "bot": None,
                    "action": None,
                    "outcome": "internal_error",
                })
            raise
        return response


class StagingExecutorGatewayClient:
    """Bot-scoped JSON client over an injected, timeout-enforcing transport."""

    def __init__(self, *, transport, token_provider, timeout_seconds):
        if not callable(transport) or not callable(token_provider):
            raise ValueError("injected gateway transport and token provider required")
        if (type(timeout_seconds) not in (int, float)
                or not 0 < timeout_seconds <= 10):
            raise ValueError("gateway request timeout must be at most 10 seconds")
        self._transport = transport
        self._token_provider = token_provider
        self._timeout_seconds = float(timeout_seconds)

    def __call__(self, *, bot, coin, action):
        if (type(bot) is not str or bot not in BOTS
                or type(coin) is not str or not coin.isascii()
                or not coin.isalnum() or coin != coin.upper()
                or type(action) is not str or action not in ENTRY_ACTIONS):
            raise GatewayClientError("invalid staging gateway request")
        try:
            token = self._token_provider(bot)
        except Exception as error:
            raise GatewayClientError("staging bearer token unavailable") from error
        if type(token) is not str or not token or len(token) > 16384:
            raise GatewayClientError("staging bearer token unavailable")

        body = json.dumps(
            {"bot": bot, "coin": coin, "action": action},
            separators=(",", ":"),
        ).encode("utf-8")
        if not 0 < len(body) <= MAX_REQUEST_BYTES:
            raise GatewayClientError("staging gateway request exceeds limit")
        try:
            response = self._transport(
                method="POST",
                path=ENTRY_CLAIM_PATH,
                headers={
                    "Authorization": "Bearer " + token,
                    "Content-Type": "application/json",
                },
                body=body,
                timeout=self._timeout_seconds,
            )
        except Exception as error:
            raise GatewayClientError("staging gateway transport failed") from error
        if (not isinstance(response, tuple) or len(response) != 2
                or type(response[0]) is not int or type(response[1]) is not bytes
                or len(response[1]) > MAX_RESPONSE_BYTES):
            raise GatewayClientError("invalid staging gateway response")
        status, response_body = response
        if status != 200:
            raise GatewayClientError(
                f"staging gateway rejected request with status {status}"
            )
        try:
            payload = json.loads(response_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            raise GatewayClientError("invalid staging gateway response") from error
        if (not isinstance(payload, dict)
                or set(payload) != {"reservation_claimed", "intent_claimed"}
                or payload["reservation_claimed"] is not True
                or payload["intent_claimed"] is not True):
            raise GatewayClientError("staging gateway did not confirm both claims")
        return payload


class StagingExecutorGatewayHost:
    """Validated WSGI app plus factory for independently injected clients."""

    def __init__(self, *, app, signing_keys, issuer, audience):
        self.app = app
        self._signing_keys = dict(signing_keys)
        self._issuer = issuer
        self._audience = audience

    def create_client(self, *, transport,
                      token_provider=None,
                      timeout_seconds=DEFAULT_REQUEST_TIMEOUT_SECONDS):
        if token_provider is None:
            token_provider = lambda bot: create_staging_executor_token(
                bot=bot,
                signing_key=self._signing_keys[bot],
                issuer=self._issuer,
                audience=self._audience,
            )
        return StagingExecutorGatewayClient(
            transport=transport,
            token_provider=token_provider,
            timeout_seconds=timeout_seconds,
        )


def create_staging_executor_gateway_host(
    *,
    secret_provider,
    signing_key_refs,
    database_password_refs,
    expected_logins,
    connection_factory_builder,
    issuer,
    audience,
    audit_sink,
):
    """Resolve synthetic/staging secrets, verify DB isolation, then return WSGI host.

    The builder must honor sslmode=verify-full and the supplied connection,
    statement, and lock timeouts. Startup verifies active PostgreSQL TLS.
    No listener or transport is created. A failed check prevents app creation.
    """
    _validate_bot_mapping(signing_key_refs, "signing-key reference")
    _validate_bot_mapping(database_password_refs, "database-password reference")
    _validate_bot_mapping(expected_logins, "database LOGIN")
    if type(issuer) is not str or not issuer.strip():
        raise GatewayStartupError("trusted staging issuer required")
    if type(audience) is not str or not audience.strip():
        raise GatewayStartupError("trusted staging audience required")
    if not callable(connection_factory_builder) or not callable(audit_sink):
        raise GatewayStartupError("connection builder and audit sink are required")

    logins = tuple(expected_logins.values())
    refs = tuple(signing_key_refs.values()) + tuple(database_password_refs.values())
    if (any(type(login) is not str or not login
            or login.lower() in _DISALLOWED_LOGINS for login in logins)
            or len(set(logins)) != len(BOTS)):
        raise GatewayStartupError("three distinct restricted LOGINs are required")
    if (any(type(reference) is not str or not reference.strip() for reference in refs)
            or len(set(refs)) != len(refs)):
        raise GatewayStartupError("distinct per-bot secret references are required")

    signing_keys = {}
    database_passwords = {}
    for bot in BOTS:
        key_value = _resolve_secret(secret_provider, signing_key_refs[bot])
        key = key_value.encode("utf-8") if type(key_value) is str else key_value
        if len(key) < 32:
            raise GatewayStartupError("staging signing key is too short")
        signing_keys[bot] = key
        password_value = _resolve_secret(
            secret_provider, database_password_refs[bot]
        )
        password = (
            password_value.encode("utf-8")
            if type(password_value) is str else password_value
        )
        database_passwords[bot] = password
    if (len(set(signing_keys.values())) != len(BOTS)
            or len(set(database_passwords.values())) != len(BOTS)):
        raise GatewayStartupError("per-bot credentials must be distinct")

    connection_factories = {}
    for bot in BOTS:
        try:
            factory = connection_factory_builder(
                bot=bot,
                login=expected_logins[bot],
                password=database_passwords[bot],
                sslmode="verify-full",
                connect_timeout=DATABASE_CONNECT_TIMEOUT_SECONDS,
                statement_timeout_ms=DATABASE_STATEMENT_TIMEOUT_MS,
                lock_timeout_ms=DATABASE_LOCK_TIMEOUT_MS,
            )
        except Exception as error:
            raise GatewayStartupError(
                f"database connection factory unavailable for {bot}"
            ) from error
        if not callable(factory):
            raise GatewayStartupError(
                f"database connection factory unavailable for {bot}"
            )
        connection_factories[bot] = factory

    for bot in BOTS:
        _check_login_permissions(
            connection_factories[bot], expected_logins[bot], bot
        )

    app = create_staging_executor_entry_app(
        signing_keys=signing_keys,
        connection_factories=connection_factories,
        expected_logins=expected_logins,
        issuer=issuer,
        audience=audience,
    )
    return StagingExecutorGatewayHost(
        app=_AuditedWSGIApp(app, audit_sink),
        signing_keys=signing_keys,
        issuer=issuer,
        audience=audience,
    )
