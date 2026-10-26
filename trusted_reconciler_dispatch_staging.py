"""Offline receiving-side gateway boundary for staging reconciliation.

The caller supplies only a token, operation and validated arguments. The
server supplies the restricted reconciler RPC adapter and signing key.
This is NOT an HTTP listener, deployed credential mapping, or live service.
"""
from trusted_reconciler_authenticated_staging import (
    reconcile_entry_with_token, reconcile_release_with_token,
)
from trusted_reconciler_gateway_jwt_staging import verify_staging_jwt

_OPERATIONS = {
    "reconcile_entry": reconcile_entry_with_token,
    "reconcile_release": reconcile_release_with_token,
}

def dispatch_staging_reconciliation(request, *, info, address, reconciler_rpc,
                                    signing_key, issuer, audience, now):
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
                    "issuer", "audience", "now", "authorized"}:
        raise PermissionError("caller cannot inject trusted dependencies")
    token = request["token"]
    # Verify before selecting an operation or touching trusted dependencies.
    verify_staging_jwt(token, signing_key, issuer=issuer, audience=audience, now=now)
    return _OPERATIONS[operation](
        info, address, reconciler_rpc, auth_token=token, signing_key=signing_key,
        issuer=issuer, audience=audience, now=now, **args,
    )
