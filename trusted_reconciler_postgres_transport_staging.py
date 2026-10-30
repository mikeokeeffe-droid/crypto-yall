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
        ("p_coin", "p_bot", "p_token", "p_exchange_flat", "p_no_open_orders")),
    "release_closed_bot_position": (
        "select public.release_closed_bot_position(%s,%s,%s,%s,%s)",
        ("p_coin", "p_bot", "p_token", "p_exchange_flat", "p_no_open_orders")),
    "release_resolved_bot_entry_intent": (
        "select public.release_resolved_bot_entry_intent(%s,%s,%s,%s,%s,%s,%s,%s)",
        ("p_coin", "p_bot", "p_token", "p_exchange_order_id",
         "p_final_status", "p_zero_fills", "p_exchange_flat",
         "p_no_open_orders")),
    "get_bot_entry_reconciliation_intent": (
        "select status, exchange_order_id, submitted_at_ms, requested_size "
        "from public.get_bot_entry_reconciliation_intent(%s,%s,%s)",
        ("p_coin", "p_bot", "p_token")),
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
        if function == "release_resolved_bot_entry_intent":
            if (type(params["p_coin"]) is not str
                    or not params["p_coin"].isascii()
                    or not params["p_coin"].isalnum()
                    or params["p_coin"] != params["p_coin"].upper()
                    or params["p_bot"] not in {"aggressive", "intraday", "daily"}
                    or type(params["p_exchange_order_id"]) is not str
                    or not params["p_exchange_order_id"].strip()
                    or params["p_final_status"] not in {
                        "canceled", "cancelled", "rejected", "expired"
                    }
                    or any(params[name] is not True for name in (
                        "p_zero_fills", "p_exchange_flat", "p_no_open_orders"
                    ))):
                raise PermissionError("invalid verified no-fill resolution")
        with connection_factory() as conn:
            with conn.transaction():
                identity = conn.execute(
                    "select session_user, current_user"
                ).fetchone()
                if identity != (expected_login, expected_login):
                    raise PermissionError("database principal mismatch")
                result = conn.execute(statement, values).fetchone()
                if function == "get_bot_entry_reconciliation_intent":
                    if result is None:
                        return None
                    return {
                        "status": result[0],
                        "exchange_order_id": result[1],
                        "submitted_at_ms": result[2],
                        "requested_size": (
                            float(result[3]) if result[3] is not None else None
                        ),
                    }
                return result[0] is True
    return rpc
