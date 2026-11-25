"""Synthetic Testnet-only gateway authorization core: OFFLINE REVIEW ONLY.

There is intentionally NO socket, TLS client, IPC listener, proxy, firewall
configuration, service, auto-run or CLI. Nothing here can contact an exchange.

A future independent gateway MUST authenticate the process/IPC caller, own its
network namespace and enforce egress separately. An untrusted client must not
be able to instantiate this class or supply arbitrary HTTP bytes to transport.
"""
import json
import secrets
import time

from readonly_connection_review.testnet_egress_policy_review_offline import (
    FIXED_ACCOUNT, PolicyHold, TYPES, URL
)

# Fixed, reviewed bounds. Never imported from a mutable environment variable.
MAX_LEASE_AGE_SECONDS = 30
MAX_REQUESTS = 2
MAX_REQUEST_BYTES = 256


class OfflineGatewayGate:
    """Deterministic one-lease/one-sequence decision core.

    This object is a test fixture for policy review, not a security boundary:
    an actual gateway must independently authenticate clients, avoid replay
    across process restarts, and isolate direct and alternate network paths.
    """

    def __init__(self, *, clock=None):
        self._clock = clock if clock is not None else time.monotonic
        self._lease_nonce = None
        self._expires_at = None
        self._next = 0
        self._spent = True

    def begin_offline_lease(self, *, approval, test_nonce):
        """Prepare exactly one synthetic lease from an external review signal.

        'approval' is a test-only fixture flag; NOT an identity, credential,
        or production approval. This method grants NO network authority.
        """
        if approval is not True or self._lease_nonce is not None:
            raise PolicyHold("synthetic lease not approved or already used")
        if (type(test_nonce) is not str or len(test_nonce) != 32
                or any(c not in "0123456789abcdef" for c in test_nonce)):
            raise PolicyHold("invalid synthetic nonce")
        self._lease_nonce = test_nonce
        self._expires_at = self._clock() + MAX_LEASE_AGE_SECONDS
        self._next = 0
        self._spent = False

    def review_step(self, *, nonce, step, caller_request=None):
        """Authorize a fixed *synthetic* frame for the next reviewed step.

        No authority to send these bytes on a network. Reject caller-supplied
        URL, method, body, path or account rather than trusting or sanitizing.
        """
        if (self._spent or self._lease_nonce is None
                or type(nonce) is not str
                or not secrets.compare_digest(nonce, self._lease_nonce)):
            raise PolicyHold("invalid or spent synthetic lease")
        if (self._clock() > self._expires_at or type(step) is not int
                or step != self._next + 1):
            self._spent = True  # Abort the lease on stale/out-of-order request
            raise PolicyHold("stale or out-of-order synthetic step")
        if caller_request is not None:
            self._spent = True
            raise PolicyHold("caller-provided HTTP request forbidden")
        kind = TYPES[self._next]
        body = json.dumps(
            {"type": kind, "user": FIXED_ACCOUNT, "dex": ""},
            separators=(",", ":"), ensure_ascii=True
        )
        if len(body.encode("ascii")) > MAX_REQUEST_BYTES:
            self._spent = True
            raise PolicyHold("synthetic request too large")
        self._next += 1
        if self._next >= MAX_REQUESTS:
            self._spent = True
        return {
            "scheme": URL[0], "host": URL[1], "port": URL[2],
            "method": URL[3], "path": URL[4], "body": body
        }

    @property
    def finished(self):
        return self._spent
