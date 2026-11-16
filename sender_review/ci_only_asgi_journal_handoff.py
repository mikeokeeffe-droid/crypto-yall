"""In-process ASGI -> disposable PostgreSQL journal bridge, TEST HARNESS ONLY.

Not a deployable ASGI application (requires extra explicit fixture args).
No listener, outbound HTTP, exchange SDK, wallet signer or live-account role.
It reuses the existing always-HOLD ASGI validator and the offline signed
fixture-to-journal function. A successful fake DB receipt is NEVER an order
acknowledgement. Only the CI-tagged loopback sender_review_test DB is touched.
"""
from dataclasses import dataclass
import json
import os

from sender_review.asgi_review_only_ingress import review_only_asgi_app
from sender_review.ci_only_remote_journal_boundary import (
    review_remote_fixture_to_disposable_journal_offline,
)


@dataclass(frozen=True)
class CIOnlyAsgiJournalReview:
    state: str = "HOLD"
    journal_recorded: bool = False
    # These are always false; fixture signature ≠ runtime authentication.
    runtime_identity_authenticated: bool = False
    request_authorized: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    signing_enabled: bool = False


async def inspect_asgi_to_disposable_journal_offline(
    *, scope, receive, send, trusted_fixture_keys,
    fixture_now_seconds, fixed_test_account, db_password,
):
    """Run one in-process fake request through HTTP validation and CI journal.

    An unrecognized/malformed response from the review-only ASGI handler
    never enters the journal. The caller receives ONLY the original ASGI
    HTTP 4xx or 503 HOLD, even when a disposable journal record is written.
    This function requires explicit fixture arguments and is NOT a callable
    ASGI server application. Never wire it to an actual network listener.
    """
    denied = CIOnlyAsgiJournalReview()
    received_chunks = []
    request_complete = False
    request_invalid = False
    responses = []
    # Capture immutable request metadata before untrusted receive callbacks
    # can mutate the scope/header list after the ASGI validator checks it.
    try:
        initial_request = (
            scope.get("type"), scope.get("method"), scope.get("path"),
            scope.get("raw_path"), scope.get("query_string"),
            tuple(tuple(item) for item in scope["headers"]),
        )
    except (TypeError, ValueError, AttributeError, KeyError):
        initial_request = None

    async def local_receive():
        nonlocal request_complete, request_invalid
        message = await receive()
        # A spoofed HOLD response must not journal a partially read stream,
        # a disconnect or a second message after the terminal body.
        if type(message) is not dict or message.get("type") != "http.request":
            request_invalid = True
        elif (request_complete
              or type(message.get("body", b"")) is not bytes
              or type(message.get("more_body", False)) is not bool):
            request_invalid = True
        else:
            received_chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                request_complete = True
        return message

    async def local_send(message):
        responses.append(message)

    try:
        await review_only_asgi_app(scope, local_receive, local_send)
    except Exception:
        # The untrusted stream/handler must never cause a success response.
        response = b'{"state":"HOLD","reason":"invalid review request"}'
        await send({
            "type": "http.response.start", "status": 503,
            "headers": [(b"content-type", b"application/json"),
                        (b"cache-control", b"no-store"),
                        (b"content-length", str(len(response)).encode())],
        })
        await send({"type": "http.response.body", "body": response})
        return denied

    # ASGI disconnect is intentionally silent, not an acknowledged request.
    if not responses:
        return denied

    # An accidental future 2xx or 3xx from the validator is NOT forwarded.
    if (
        len(responses) != 2
        or type(responses[0]) is not dict
        or type(responses[1]) is not dict
        or responses[0].get("type") != "http.response.start"
        or type(responses[0].get("status")) is not int
        or responses[0]["status"] < 400
        or responses[1].get("type") != "http.response.body"
        or type(responses[1].get("body")) is not bytes
        or responses[1].get("more_body", False) is not False
    ):
        response = b'{"state":"HOLD","reason":"review boundary unavailable"}'
        await send({
            "type": "http.response.start", "status": 503,
            "headers": [(b"content-type", b"application/json"),
                        (b"content-length", str(len(response)).encode())],
        })
        await send({"type": "http.response.body", "body": response})
        return denied

    # Only the exact normal (not failed) 503 from the checked-in handler
    # is eligible for a disposable fake journal receipt.
    try:
        same_request = initial_request is not None and initial_request == (
            scope.get("type"), scope.get("method"), scope.get("path"),
            scope.get("raw_path"), scope.get("query_string"),
            tuple(tuple(item) for item in scope["headers"]),
        )
    except (TypeError, ValueError, AttributeError, KeyError):
        same_request = False
    expected = b'{"state":"HOLD","reason":"no authenticated sender deployed"}'
    eligible = (
        same_request
        and type(scope) is dict
        and scope.get("type") == "http"
        and scope.get("method") == "POST"
        and scope.get("path") == "/v1/review-only/entry-intents"
        and responses[0].get("status") == 503
        and responses[1].get("body") == expected
        and responses[0].get("type") == "http.response.start"
        and responses[1].get("type") == "http.response.body"
        and responses[1].get("more_body", False) is False
        and os.environ.get("SENDER_REVIEW_DISPOSABLE_CI") == "1"
        and os.environ.get("PGDATABASE") == "sender_review_test"
        and os.environ.get("PGHOST") == "127.0.0.1"
        and request_complete
        and not request_invalid
        and 0 < len(received_chunks) <= 32
    )
    recorded = False
    if eligible:
        try:
            headers = scope.get("headers")
            names = {}
            if type(headers) not in (list, tuple):
                raise ValueError("invalid headers")
            for name, value in headers:
                if type(name) is not bytes or type(value) is not bytes:
                    raise ValueError("invalid header pair")
                lower = name.lower()
                if lower in names or lower not in (
                    b"authorization", b"content-type", b"content-length"
                ):
                    raise ValueError("headers not eligible for CI journal")
                names[lower] = value
            if set(names) not in (
                {b"authorization", b"content-type"},
                {b"authorization", b"content-type", b"content-length"},
            ):
                raise ValueError("required headers absent")
            auth = names[b"authorization"]
            if not auth.startswith(b"Bearer "):
                raise ValueError("invalid bearer")
            token = auth[7:].decode("ascii")
            payload = b"".join(received_chunks)
            if not 0 < len(payload) <= 1024:
                raise ValueError("invalid payload")
            audit = review_remote_fixture_to_disposable_journal_offline(
                method="POST", path="/v1/review-only/entry-intents",
                headers=[
                    ("Authorization", "Bearer " + token),
                    ("Content-Type", "application/json"),
                ],
                body=payload, trusted_fixture_keys=trusted_fixture_keys,
                fixture_now_seconds=fixture_now_seconds,
                fixed_test_account=fixed_test_account,
                db_password=db_password,
            )
            recorded = (
                audit.state == "persisted_remote_fixture_review_only_HOLD"
                and audit.journal_recorded is True
            )
        except (ValueError, TypeError, UnicodeError, KeyError):
            pass

    # Never expose whether the fake journal wrote a row, let alone a token.
    for response in responses:
        await send(response)
    return CIOnlyAsgiJournalReview(journal_recorded=recorded)
