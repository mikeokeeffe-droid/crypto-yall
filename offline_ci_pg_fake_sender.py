"""Offline-only PostgreSQL journal-before-fake sender demonstration.

NO trading SDK, HTTP requests, private keys, production database, live
order, close, or signing authority. This deliberately cannot dispatch orders.
Only disposable safety_test PostgreSQL; a synthetic result is never ownership.
"""
from dataclasses import dataclass
import os
import re
import uuid

from offline_shared_sender_prototype import FakeExchange

_CLOID = re.compile(r"0x[0-9a-f]{32}\Z", re.ASCII)


@dataclass(frozen=True)
class OfflinePgFakeDispatchResult:
    state: str
    reason: str = ""
    submit_authorized: bool = False


def simulate_postgres_fake_dispatch_once(*, sender_connection_factory,
                                         token, fence, fake):
    """Commit exactly one DB marker before recording a fake order attempt.

    The database SECURITY DEFINER RPC validates session_user and performs
    the atomic compare-and-swap; no caller can mutate the journal directly.
    Losing the reply, commit failure, or any ambiguity returns HOLD, and the
    durable attempt is never retried automatically.
    """
    held = OfflinePgFakeDispatchResult("hold", "no fake dispatch permission")
    if (os.getenv("ISOLATED_POSTGRES_CI") != "1"
            or os.getenv("PGDATABASE") != "safety_test"
            or os.getenv("PGHOST") not in ("localhost", "127.0.0.1")
            or not callable(sender_connection_factory)
            or type(token) is not uuid.UUID
            or type(fence) is not int or fence <= 0
            or type(fake) is not FakeExchange):
        return held
    cloid = None
    try:
        # The context manager COMMITS the marker before the fake callback.
        # Returning inside the context would risk reporting pre-commit success.
        with sender_connection_factory() as conn:
            if conn.info.host not in ("localhost", "127.0.0.1", "::1"):
                return held
            identity = conn.execute(
                "select current_database(), session_user, current_user"
            ).fetchone()
            if identity != (
                "safety_test", "ci_sender_worker", "ci_sender_worker",
            ):
                return held
            row = conn.execute(
                "select marked,stored_cloid "
                "from public.ci_sender_mark_unknown(%s,%s)",
                (token, fence),
            ).fetchone()
            if (row is None or row[0] is not True
                    or type(row[1]) is not str
                    or _CLOID.fullmatch(row[1]) is None):
                return held
            cloid = row[1]
        # The database connection completed its COMMIT successfully.
    except Exception:
        return OfflinePgFakeDispatchResult("hold", "journal unavailable or ambiguous")

    try:
        fake.record_fake_attempt(str(token), cloid)
    except Exception:
        return OfflinePgFakeDispatchResult("hold", "fake acknowledgement unknown")

    return OfflinePgFakeDispatchResult(
        "observed_unverified",
        "fixture-only attempt; never confirms exchange ownership",
    )
