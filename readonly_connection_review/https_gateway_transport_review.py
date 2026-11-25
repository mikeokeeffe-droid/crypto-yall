"""Testnet HTTPS transport *integration harness* — REVIEW, NOT DEPLOYABLE.

Binds synthetic two-request gateway frames to the pre-existing fixed
Hyperliquid Testnet /info account reader. There is NO default HTTP transport,
CLI, listener, service, network enablement, trading signing or deployment.
Offline tests provide mocked HTTPS connection factories.

A supplied factory COULD create real sockets: therefore this is NOT an
enforced network sandbox and must NOT be wired to any host service without
an independently reviewed gateway, verified TLS/egress boundary and explicit
one-shot operator approval. This module grants no such approval.
"""
from readonly_connection_review import testnet_account_read_review_only as reader
from readonly_connection_review.testnet_egress_policy_review_offline import (
    PolicyHold, inspect_synthetic_requests,
)

# The public-account counts are the ONLY data exposed to a future IPC caller.


def review_fixed_info_transport(frames, *, policy, connection_factory=None):
    """Validate both frames before any IO, then issue two fixed read-only POSTs.

    The mandatory connection_factory is a test injection; there is
    deliberately no default real-network path. This checks source-level
    request constraints only, NOT kernel-level egress limits.
    """
    inspect_synthetic_requests(policy, frames)
    if connection_factory is None or not callable(connection_factory):
        raise PolicyHold("network transport is not provided or approved")

    counts = []
    for kind in ("clearinghouseState", "openOrders"):
        # The reader owns the fixed method, URL, body, response limits and TLS
        # factory invocation; no frame-provided URL/body is forwarded.
        count = reader.fetch_info(kind, connection_factory=connection_factory)
        if type(count) is not int or count < 0 or count > 5000:
            raise PolicyHold("invalid read-only account count")
        counts.append(count)
    return {"positions": counts[0], "open_orders": counts[1]}
