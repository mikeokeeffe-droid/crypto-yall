"""Staging-only executor PostgreSQL transport; never places exchange orders.

The caller supplies a connection factory for a dedicated, independently
provisioned LOGIN role. This module does not load credentials or change grants.
Production use requires independent security review and executor integration.
"""
from uuid import UUID

_ALLOWED = {
    "try_reserve_bot_entry": (
        "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
        ("p_coin", "p_bot", "p_token", "p_ttl_seconds")),
    "claim_bot_entry_intent": (
        "select public.claim_bot_entry_intent(%s,%s,%s)",
        ("p_coin", "p_bot", "p_token")),
    "release_bot_entry": (
        "select public.release_bot_entry(%s,%s,%s)",
        ("p_coin", "p_bot", "p_token")),
}
_BOTS = frozenset(("aggressive", "intraday", "daily"))


class ExecutorDatabaseError(RuntimeError):
    """A restricted PostgreSQL operation failed; the entry must remain blocked."""


class ExecutorIdentityMismatch(PermissionError):
    """The database session did not use the configured restricted LOGIN."""


def restricted_executor_rpc(connection_factory, *, expected_login, expected_bot):
    """Build a bot- and LOGIN-bound RPC callable for the staging gateway."""
    if (not callable(connection_factory) or type(expected_login) is not str
            or not expected_login or expected_login in
            {"postgres", "service_role", "bot_entry_executor_trial", "bot_reconciler"}
            or type(expected_bot) is not str or expected_bot not in _BOTS):
        raise ValueError("dedicated executor login and connection factory required")

    def rpc(function, params):
        if function not in _ALLOWED or type(params) is not dict:
            raise PermissionError("executor RPC denied")
        statement, keys = _ALLOWED[function]
        if set(params) != set(keys):
            raise PermissionError("unexpected executor RPC arguments")
        coin, bot, token = (params[key] for key in keys[:3])
        if (type(coin) is not str or not coin or not coin.isascii()
                or not coin.isalnum() or coin != coin.upper()
                or type(bot) is not str or bot not in _BOTS):
            raise ValueError("invalid coin or bot")
        if bot != expected_bot:
            raise PermissionError("executor database identity is bound to another bot")
        UUID(str(token))
        if function == "try_reserve_bot_entry":
            ttl = params["p_ttl_seconds"]
            if type(ttl) is not int or not 30 <= ttl <= 600:
                raise ValueError("invalid reservation TTL")
        values = tuple(params[key] for key in keys)
        try:
            with connection_factory() as conn:
                with conn.transaction():
                    identity = conn.execute(
                        "select session_user, current_user").fetchone()
                    if identity != (expected_login, expected_login):
                        raise ExecutorIdentityMismatch("database principal mismatch")
                    return conn.execute(statement, values).fetchone()[0] is True
        except ExecutorIdentityMismatch:
            raise
        except Exception as error:
            raise ExecutorDatabaseError(
                "restricted executor database operation failed"
            ) from error

    return rpc
