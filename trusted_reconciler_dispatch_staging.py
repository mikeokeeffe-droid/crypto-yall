"""Offline receiving-side gateway boundary for staging reconciliation.

The caller supplies only a token, operation and validated arguments. The
server supplies the restricted reconciler RPC adapter and signing key.
This is NOT an HTTP listener, deployed credential mapping, or live service.
"""
from trusted_reconciler_authenticated_staging import (
    reconcile_entry_with_token, reconcile_release_with_token,
)
from math import isfinite
from trusted_reconciler_gateway_jwt_staging import verify_staging_jwt
from staging_executor_gateway_contract import BOTS
from trusted_reconciler_service_staging import ServiceResult

_ARGUMENTS = {
    "reconcile_entry": frozenset({"coin", "bot", "token"}),
    "reconcile_release": frozenset({"coin", "bot", "token"}),
}

_OPERATIONS = {
    "reconcile_entry": reconcile_entry_with_token,
    "reconcile_release": reconcile_release_with_token,
}

def dispatch_staging_reconciliation(request, *, info, address, reconciler_rpc,
                                    signing_keys, issuer, audience, now, clock):
    """Fail closed before touching the exchange or database adapter."""
    if not isinstance(request, dict) or set(request) != {"token", "operation", "args"}:
        raise PermissionError("invalid gateway request")
    operation = request["operation"]
    if not isinstance(operation, str) or operation not in _OPERATIONS:
        raise PermissionError("unsupported reconciliation operation")
    args = request["args"]
    if not isinstance(args, dict) or not args or any(
        not isinstance(k, str) or k.startswith("_") for k in args
    ):
        raise PermissionError("invalid reconciliation arguments")
    if set(args) & {"info", "address", "rpc", "auth_token", "signing_key",
                    "signing_keys",
                    "issuer", "audience", "now", "authorized", "clock"}:
        raise PermissionError("caller cannot inject trusted dependencies")
    if set(args) != _ARGUMENTS[operation]:
        raise PermissionError("unexpected or missing reconciliation arguments")
    if args["bot"] not in BOTS:
        raise PermissionError("unsupported staging bot")
    if (type(args["coin"]) is not str or not args["coin"].isascii()
            or not args["coin"].isalnum() or args["coin"] != args["coin"].upper()
            or type(args["token"]) is not str or not args["token"]):
        raise PermissionError("invalid durable intent identity")
    if (not isinstance(signing_keys, dict) or set(signing_keys) != BOTS
            or any(type(key) is not bytes or len(key) < 32
                   for key in signing_keys.values())
            or len(set(signing_keys.values())) != len(BOTS)):
        raise PermissionError("distinct per-bot reconciler signing keys required")
    signing_key = signing_keys[args["bot"]]
    token = request["token"]
    # Verify before invoking any trusted dependencies.
    principal = verify_staging_jwt(
        token, signing_key, issuer=issuer, audience=audience, now=now
    )
    if principal.subject != "reconciler:" + args["bot"]:
        raise PermissionError("reconciler identity is not bound to requested bot")
    trusted_args = dict(args)
    if operation == "reconcile_entry":
        intent = reconciler_rpc(
            "get_bot_entry_reconciliation_intent",
            {
                "p_coin": args["coin"],
                "p_bot": args["bot"],
                "p_token": args["token"],
            },
        )
        if not isinstance(intent, dict) or set(intent) != {
            "status", "exchange_order_id", "submitted_at_ms", "requested_size",
        }:
            return ServiceResult(False, "durable entry intent unavailable; fence retained")
        order_id = intent["exchange_order_id"]
        if (type(intent["status"]) is not str
                or intent["status"] not in {"submitted", "uncertain", "filled"}
                or type(order_id) is not str or not order_id.isdecimal()
                or type(intent["submitted_at_ms"]) is not int
                or intent["submitted_at_ms"] < 0
                or type(intent["requested_size"]) not in (int, float)
                or not isfinite(intent["requested_size"])
                or intent["requested_size"] <= 0):
            return ServiceResult(
                False,
                "durable exchange order identity unavailable; fence retained",
            )
        trusted_args.update({
            "order_id": order_id,
            "order_start_ms": intent["submitted_at_ms"],
            "requested_size": intent["requested_size"],
        })
    return _OPERATIONS[operation](
        info, address, reconciler_rpc, auth_token=token, signing_key=signing_key,
        issuer=issuer, audience=audience, now=now, clock=clock, **trusted_args,
    )
