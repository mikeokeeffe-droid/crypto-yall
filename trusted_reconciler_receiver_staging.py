"""Callable-only authenticated receiver for staging reconciliation.

The WSGI app starts no listener. Exchange clients, account addresses, JWT keys,
database connection factories, and LOGIN identities are server-controlled.
"""
import json
import re
import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone

from staging_executor_gateway_contract import BOTS
from trusted_reconciler_dispatch_staging import dispatch_staging_reconciliation
from trusted_reconciler_postgres_transport_staging import (
    restricted_reconciler_rpc,
)

RECONCILIATION_PATH = "/staging/reconciliation"
MAX_REQUEST_BYTES = 4096
_DISALLOWED_LOGINS = frozenset({
    "postgres", "service_role", "bot_reconciler", "bot_entry_executor_trial",
})
_OPERATIONS = frozenset({"reconcile_entry", "reconcile_release"})
_IDENTITY_SQL = """
select session_user::text, current_user::text, r.rolcanlogin, r.rolsuper,
       r.rolinherit, r.rolcreatedb, r.rolcreaterole, r.rolreplication,
       r.rolbypassrls,
       pg_catalog.pg_has_role(session_user, 'bot_reconciler', 'MEMBER'),
       not pg_catalog.has_schema_privilege(current_user, 'public', 'CREATE'),
       not exists (
         select 1 from pg_catalog.pg_roles inherited
         where inherited.rolname not in (session_user::text, 'bot_reconciler')
           and pg_catalog.pg_has_role(session_user, inherited.oid, 'MEMBER')
       )
from pg_catalog.pg_roles r
where r.rolname = session_user
"""
_PRIVILEGE_SQL = """
select
  pg_catalog.has_function_privilege(current_user,
    'public.get_bot_entry_reconciliation_intent(text,text,uuid)', 'EXECUTE')
  and pg_catalog.has_function_privilege(current_user,
    'public.record_bot_position_owner(text,text,uuid,text,boolean)', 'EXECUTE')
  and pg_catalog.has_function_privilege(current_user,
    'public.mark_bot_position_closed(text,text,uuid,boolean,boolean)', 'EXECUTE')
  and pg_catalog.has_function_privilege(current_user,
    'public.release_closed_bot_position(text,text,uuid,boolean,boolean)', 'EXECUTE')
  and pg_catalog.has_function_privilege(current_user,
    'public.release_resolved_bot_entry_intent(text,text,uuid,text,text,boolean,boolean,boolean)',
    'EXECUTE')
  and pg_catalog.has_function_privilege(current_user,
    'public.is_bot_reconciler_identity(text)', 'EXECUTE')
  and not pg_catalog.has_function_privilege(current_user,
    'public.try_reserve_bot_entry(text,text,uuid,integer)', 'EXECUTE')
  and not pg_catalog.has_function_privilege(current_user,
    'public.claim_bot_entry_intent(text,text,uuid)', 'EXECUTE')
  and not pg_catalog.has_function_privilege(current_user,
    'public.release_bot_entry(text,text,uuid)', 'EXECUTE')
  and not pg_catalog.has_function_privilege(current_user,
    'public.record_bot_entry_order(text,text,uuid,text,bigint,numeric,text)',
    'EXECUTE')
  and not pg_catalog.has_function_privilege(current_user,
    'public.resolve_bot_entry_intent(text,text,uuid)', 'EXECUTE')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_intents', 'SELECT')
  and not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_entry_intents', 'SELECT')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_reservations', 'SELECT')
  and not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_entry_reservations', 'SELECT')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_position_owners', 'SELECT')
  and not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_position_owners', 'SELECT')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_intents', 'INSERT')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_intents', 'UPDATE')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_intents', 'DELETE')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_intents', 'TRUNCATE')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_intents', 'REFERENCES')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_intents', 'TRIGGER')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_reservations', 'INSERT')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_reservations', 'UPDATE')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_reservations', 'DELETE')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_reservations', 'TRUNCATE')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_reservations', 'REFERENCES')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_reservations', 'TRIGGER')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_position_owners', 'INSERT')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_position_owners', 'UPDATE')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_position_owners', 'DELETE')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_position_owners', 'TRUNCATE')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_position_owners', 'REFERENCES')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_position_owners', 'TRIGGER')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_reconciler_identities', 'SELECT')
  and not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_reconciler_identities', 'SELECT')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_reconciler_identities', 'INSERT')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_reconciler_identities', 'UPDATE')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_reconciler_identities', 'DELETE')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_reconciler_identities', 'TRUNCATE')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_reconciler_identities', 'REFERENCES')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_reconciler_identities', 'TRIGGER')
  and not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_reconciler_identities', 'SELECT')
  and not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_reconciler_identities', 'INSERT')
  and not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_reconciler_identities', 'UPDATE')
  and not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_reconciler_identities', 'REFERENCES')
  and not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_entry_intents', 'INSERT')
  and not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_entry_intents', 'UPDATE')
  and not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_entry_intents', 'REFERENCES')
  and not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_entry_reservations', 'INSERT')
  and not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_entry_reservations', 'UPDATE')
  and not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_entry_reservations', 'REFERENCES')
  and not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_position_owners', 'INSERT')
  and not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_position_owners', 'UPDATE')
  and not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_position_owners', 'REFERENCES')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_executor_identities', 'SELECT')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_executor_identities', 'INSERT')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_executor_identities', 'UPDATE')
  and not pg_catalog.has_table_privilege(current_user,
    'public.bot_entry_executor_identities', 'DELETE')
  and not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_entry_executor_identities', 'SELECT')
  and not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_entry_executor_identities', 'INSERT')
  and not pg_catalog.has_any_column_privilege(current_user,
    'public.bot_entry_executor_identities', 'UPDATE')
  and not exists (
    select 1 from pg_catalog.pg_proc p
    join pg_catalog.pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and pg_catalog.has_function_privilege(current_user, p.oid, 'EXECUTE')
      and p.oid not in (
        pg_catalog.to_regprocedure(
          'public.get_bot_entry_reconciliation_intent(text,text,uuid)'),
        pg_catalog.to_regprocedure(
          'public.record_bot_position_owner(text,text,uuid,text,boolean)'),
        pg_catalog.to_regprocedure(
          'public.mark_bot_position_closed(text,text,uuid,boolean,boolean)'),
        pg_catalog.to_regprocedure(
          'public.release_closed_bot_position(text,text,uuid,boolean,boolean)'),
        pg_catalog.to_regprocedure(
          'public.release_resolved_bot_entry_intent(text,text,uuid,text,text,boolean,boolean,boolean)'),
        pg_catalog.to_regprocedure(
          'public.is_bot_reconciler_identity(text)')
      )
  )
"""


def _validate_mapping(value, label):
    if not isinstance(value, Mapping) or set(value) != BOTS:
        raise ValueError(f"complete per-bot {label} mapping required")


def _verify_reconciler_login(connection_factory, expected_login, expected_bot):
    try:
        with connection_factory() as connection:
            with connection.transaction():
                identity = connection.execute(_IDENTITY_SQL).fetchone()
                if (identity is None or len(identity) != 12
                        or identity[0] != expected_login
                        or identity[1] != expected_login
                        or identity[2] is not True
                        or any(identity[index] is not False
                               for index in (3, 5, 6, 7, 8))
                        or identity[4] is not True
                        or identity[9] is not True
                        or identity[10] is not True
                        or identity[11] is not True):
                    raise ValueError("reconciler database identity rejected")
                mapping = connection.execute(
                    "select public.is_bot_reconciler_identity(%s)",
                    (expected_bot,),
                ).fetchone()
                if mapping is None or mapping[0] is not True:
                    raise ValueError("reconciler LOGIN is not mapped to bot")
                privileges = connection.execute(_PRIVILEGE_SQL).fetchone()
                if privileges is None or privileges[0] is not True:
                    raise ValueError("reconciler database grants rejected")
    except Exception as error:
        raise ValueError("reconciler database preflight failed") from error


class StagingReconciliationReceiver:
    """Authenticated WSGI receiver; construction never opens a listener."""

    def __init__(
        self,
        *,
        signing_keys,
        issuer,
        audience,
        info_clients,
        account_addresses,
        connection_factories,
        expected_logins,
        audit_sink,
        now=None,
        clock=time.time,
    ):
        for configured, label in (
            (signing_keys, "signing-key"),
            (info_clients, "exchange-client"),
            (account_addresses, "account-address"),
            (connection_factories, "database connection-factory"),
            (expected_logins, "database LOGIN"),
        ):
            _validate_mapping(configured, label)
        if (type(issuer) is not str or not issuer.strip()
                or type(audience) is not str or not audience.strip()
                or not callable(audit_sink) or not callable(clock)
                or (now is not None and not callable(now))):
            raise ValueError("trusted issuer, audience, clock, and audit sink required")

        keys = tuple(signing_keys.values())
        if (any(type(key) is not bytes or len(key) < 32 for key in keys)
                or len(set(keys)) != len(BOTS)):
            raise ValueError("distinct per-bot reconciler signing keys required")
        for bot in BOTS:
            client = info_clients[bot]
            if any(not callable(getattr(client, method, None)) for method in (
                "order_status", "user_state", "open_orders", "user_fills",
                "user_fills_by_time",
            )):
                raise ValueError("server-side read-only exchange client required")
            address = account_addresses[bot]
            if type(address) is not str or not re.fullmatch(
                r"0x[0-9a-fA-F]{40}", address
            ):
                raise ValueError("valid server-side public account address required")

        logins = tuple(expected_logins.values())
        if (any(type(login) is not str or not login
                or login.lower() in _DISALLOWED_LOGINS for login in logins)
                or len(set(logins)) != len(BOTS)
                or any(not callable(factory)
                       for factory in connection_factories.values())):
            raise ValueError("three distinct restricted reconciler LOGINs required")

        self._now = now or (lambda: int(time.time()))
        self._clock = clock
        self._issuer = issuer
        self._audience = audience
        self._signing_keys = dict(signing_keys)
        self._info_clients = dict(info_clients)
        self._account_addresses = dict(account_addresses)
        self._audit_sink = audit_sink
        self._rpcs = {}
        for bot in BOTS:
            _verify_reconciler_login(
                connection_factories[bot], expected_logins[bot], bot
            )
            self._rpcs[bot] = restricted_reconciler_rpc(
                connection_factories[bot],
                expected_login=expected_logins[bot],
            )

    def __call__(self, environ, start_response):
        request_id = str(uuid.uuid4())
        bot = None
        operation = None
        status = 400
        outcome = "invalid_request"
        result = {"error": "invalid request"}

        try:
            payload = self._read_request(environ)
            bot = payload["bot"]
            operation = payload["operation"]
            if bot not in BOTS or operation not in _OPERATIONS:
                raise ValueError("invalid bot or operation")
            coin = payload["coin"]
            intent_token = payload["intent_token"]
            if (type(coin) is not str or not coin.isascii()
                    or not coin.isalnum() or coin != coin.upper()
                    or type(intent_token) is not str
                    or str(uuid.UUID(intent_token)) != intent_token):
                raise ValueError("invalid durable intent identity")

            authorization = environ.get("HTTP_AUTHORIZATION")
            if type(authorization) is not str:
                raise PermissionError("missing bearer token")
            scheme, separator, auth_token = authorization.partition(" ")
            if (not separator or scheme.lower() != "bearer" or not auth_token
                    or any(character.isspace() for character in auth_token)):
                raise PermissionError("invalid bearer token")

            response = dispatch_staging_reconciliation(
                {
                    "token": auth_token,
                    "operation": operation,
                    "args": {
                        "bot": bot,
                        "coin": coin,
                        "token": intent_token,
                    },
                },
                info=self._info_clients[bot],
                address=self._account_addresses[bot],
                reconciler_rpc=self._rpcs[bot],
                signing_keys=self._signing_keys,
                issuer=self._issuer,
                audience=self._audience,
                now=self._now(),
                clock=self._clock,
            )
            if response.confirmed:
                status = 200
                outcome = "confirmed"
                result = {"confirmed": True}
            else:
                status = 409
                outcome = "not_confirmed"
                result = {"confirmed": False, "reconciliation_required": True}
        except PermissionError:
            status = 401
            outcome = "unauthorized"
            result = {"error": "unauthorized"}
        except (KeyError, TypeError, ValueError, UnicodeDecodeError,
                RecursionError):
            status = 400
            outcome = "invalid_request"
            result = {"error": "invalid request"}
        except Exception:
            status = 503
            outcome = "reconciliation_unavailable"
            result = {"error": "reconciliation unavailable"}

        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": request_id,
            "bot": bot if bot in BOTS else None,
            "operation": operation if operation in _OPERATIONS else None,
            "status": status,
            "outcome": outcome,
        }
        try:
            self._audit_sink(event)
        except Exception:
            status = 503
            result = {
                "error": "reconciliation unavailable",
                "reconciliation_required": True,
            }
        return self._respond(start_response, status, result)

    @staticmethod
    def _read_request(environ):
        if (environ.get("PATH_INFO") != RECONCILIATION_PATH
                or environ.get("REQUEST_METHOD") != "POST"
                or environ.get("CONTENT_TYPE", "").split(";", 1)[0].strip().lower()
                != "application/json"):
            raise ValueError("unsupported request")
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

        def reject_duplicates(pairs):
            fields = {}
            for key, value in pairs:
                if key in fields:
                    raise ValueError("duplicate JSON field")
                fields[key] = value
            return fields

        payload = json.loads(raw_body.decode("utf-8"), object_pairs_hook=reject_duplicates)
        if (not isinstance(payload, dict)
                or set(payload) != {"bot", "operation", "coin", "intent_token"}
                or any(type(payload[field]) is not str for field in payload)):
            raise ValueError("invalid reconciliation fields")
        return payload

    @staticmethod
    def _respond(start_response, status, payload):
        reasons = {
            200: "OK",
            400: "Bad Request",
            401: "Unauthorized",
            409: "Conflict",
            503: "Service Unavailable",
        }
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        start_response(f"{status} {reasons[status]}", [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
        ])
        return [body]


def create_staging_reconciliation_receiver(**server_configuration):
    """Create the callable receiver after validating trusted server bindings."""
    return StagingReconciliationReceiver(**server_configuration)
