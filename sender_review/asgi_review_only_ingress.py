"""ASGI HTTP ingress adapter for reviewed ENTRY requests; permanently HOLD.

No server listener, TLS terminator, secrets, exchange SDK, DB, signer, or
order execution. This ASGI callable is NOT deployed or wired to live bots.
It accepts bounded raw HTTP messages and passes a candidate token + exact
body to the disabled server-side preflight; it ALWAYS returns HTTP 503 HOLD.

A future real service requires separately reviewed HTTPS ingress/host pinning,
GitHub OIDC issuer provenance, authenticated identity+body binding, durable
replay fencing, exchange reconciliation, and explicit operator permission.
Neither HTTP 202 nor an order acknowledgment can be produced by this adapter.
"""
import json
import re

from sender_review.request_contract import inspect_sender_entry_request_offline
from sender_review.server_oidc_preflight_review import (
    inspect_server_oidc_preflight_review,
)

_PATH = "/v1/review-only/entry-intents"
_RAW_PATH = _PATH.encode("ascii")
_ALLOWED_HEADERS = frozenset((
    b"authorization", b"content-type", b"content-length",
    b"host", b"user-agent", b"accept", b"accept-encoding", b"connection",
))
_DIGITS = re.compile(rb"[1-9][0-9]{0,3}\Z", re.ASCII)
_TOKEN_SHAPE = re.compile(
    r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\Z", re.ASCII
)


async def _reply(send, status, reason):
    body = json.dumps(
        {"state": "HOLD", "reason": reason}, separators=(",", ":"),
    ).encode("ascii")
    await send({
        "type": "http.response.start", "status": status, "headers": [
            (b"content-type", b"application/json"),
            (b"cache-control", b"no-store"),
            (b"content-length", str(len(body)).encode("ascii")),
        ],
    })
    await send({"type": "http.response.body", "body": body})


async def review_only_asgi_app(scope, receive, send):
    """Validate a raw entry-request envelope then fail closed without I/O.

    An ASGI server calling this function would be a separate deployment,
    which is NOT approved. Upstream TLS/proxy trust is also NOT established.
    """
    if type(scope) is not dict or scope.get("type") != "http":
        return
    if (scope.get("path") != _PATH
            or scope.get("raw_path", _RAW_PATH) != _RAW_PATH
            or scope.get("query_string", b"") != b""):
        await _reply(send, 404, "unknown route")
        return
    if scope.get("method") != "POST":
        await _reply(send, 405, "method not permitted")
        return
    incoming = scope.get("headers")
    if type(incoming) not in (list, tuple) or not 2 <= len(incoming) <= 16:
        await _reply(send, 400, "invalid headers")
        return
    parsed_headers = {}
    for item in incoming:
        if (type(item) not in (list, tuple) or len(item) != 2
                or type(item[0]) is not bytes or type(item[1]) is not bytes
                or len(item[0]) > 80 or len(item[1]) > 16064
                or any(c in item[0] + item[1] for c in (0, 10, 13))):
            await _reply(send, 400, "invalid headers")
            return
        name = item[0].lower()
        if (name not in _ALLOWED_HEADERS
                or name in parsed_headers):
            await _reply(send, 400, "invalid headers")
            return
        parsed_headers[name] = item[1]
    if parsed_headers.get(b"content-type") != b"application/json":
        await _reply(send, 400, "invalid content type")
        return
    auth = parsed_headers.get(b"authorization", b"")
    if not auth.startswith(b"Bearer ") or auth.count(b" ") != 1:
        await _reply(send, 401, "invalid identity envelope")
        return
    try:
        token = auth[7:].decode("ascii")
    except UnicodeError:
        await _reply(send, 401, "invalid identity envelope")
        return
    if not 100 <= len(token) <= 16000 or _TOKEN_SHAPE.fullmatch(token) is None:
        await _reply(send, 401, "invalid identity envelope")
        return
    length = parsed_headers.get(b"content-length")
    if length is not None and (_DIGITS.fullmatch(length) is None
                               or int(length) > 1024):
        await _reply(send, 413, "payload too large or ambiguous")
        return

    body = bytearray()
    # Bound message count as well as bytes; never consume an infinite stream.
    for _ in range(32):
        message = await receive()
        if type(message) is not dict:
            await _reply(send, 400, "invalid request stream")
            return
        if message.get("type") == "http.disconnect":
            return
        if (message.get("type") != "http.request"
                or type(message.get("body", b"")) is not bytes
                or type(message.get("more_body", False)) is not bool):
            await _reply(send, 400, "invalid request stream")
            return
        body.extend(message.get("body", b""))
        if len(body) > 1024:
            await _reply(send, 413, "payload too large")
            return
        if not message.get("more_body", False):
            break
    else:
        await _reply(send, 413, "too many request chunks")
        return
    if length is not None and int(length) != len(body):
        await _reply(send, 400, "length mismatch")
        return
    exact_body = bytes(body)
    if inspect_sender_entry_request_offline(body=exact_body).state != "review_only":
        await _reply(send, 400, "invalid entry contract")
        return

    # Keep the ingress permanently unable to fetch keys or authorize orders.
    # Even a future successful candidate preflight cannot change its result.
    inspect_server_oidc_preflight_review(
        token=token, request_body=exact_body,
        approved_readonly_key_fetch=False,
    )
    await _reply(send, 503, "no authenticated sender deployed")


# ASGI application object is only importable; nothing binds or starts it.
application = review_only_asgi_app
