"""Staging-only restricted PostgreSQL RPC transport.

Use a dedicated LOGIN role with only bot_reconciler grants. Do not connect as
postgres, service_role, or another privileged role and SET ROLE. No credentials
are loaded here; the gateway supplies a trusted connection factory.
"""
from uuid import UUID

_ALLOWED = {
    "record_bot_position_owner": (
        "select public.record_bot_position_owner(%s,%s,%s,%s,%s)",
        ("p_coin", "p_bot", "p_token", "p_exchange_order_id", "p_fill_verified")),
    "mark_bot_position_closed": (
        "select public.mark_bot_position_closed(%s,%s,%s,%s,%s)",
        ("p_coin", "p_bot", "p_token", "p_flat_verified", "p_no_open_orders")),
    "release_closed_bot_position": (
        "select public.release_closed_bot_position(%s,%s,%s,%s,%s)",
        ("p_coin", "p_bot", "p_token", "p_flat_verified", "p_no_open_orders")),
}


def restricted_reconciler_rpc(connection_factory, *, expected_login):
    """Return an RPC callable after enforcing dedicated session identity.

    expected_login must be a separately provisioned LOGIN role with reconciler
    privileges and no elevated membership. PostgreSQL role grants must be
    independently audited; checking current_user is necessary, not sufficient.
    """
    if (not callable(connection_factory) or type(expected_login) is not str
            or not expected_login or expected_login in
            {"postgres", "service_role", "bot_reconciler"}):
        raise ValueError("dedicated reconciler login and factory required")

    def rpc(function, params):
        if function not in _ALLOWED or type(params) is not dict:
            raise PermissionError("RPC not permitted for reconciler")
        statement, keys = _ALLOWED[function]
        if set(params) != set(keys):
            raise PermissionError("unexpected RPC parameters")
        values = tuple(params[key] for key in keys)
        UUID(str(params["p_token"]))
        with connection_factory() as conn:
            with conn.transaction():
                identity = conn.execute(
                    "select session_user, current_user"
                ).fetchone()
                if identity != (expected_login, expected_login):
                    raise PermissionError("database principal mismatch")
                return conn.execute(statement, values).fetchone()[0] is True
    return rpc
