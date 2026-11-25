"""OFFLINE-only integration of Linux peer/provenance and synthetic request gate.

Uses an ALREADY CONNECTED AF_UNIX stream socket; never opens/listens on any
socket, sends bytes, reaches an exchange, creates a lease or starts a service.
All expected identity/provenance and approval values are caller-provided test
fixtures, NOT secure production authentication. NOT DEPLOYABLE.
"""
from readonly_connection_review.kernel_unix_peer_review_offline import (
    kernel_unix_peer_credentials,
)
from readonly_connection_review.linux_process_provenance_review_offline import (
    matches_reviewed_process, read_linux_process_provenance,
)
from readonly_connection_review.offline_gateway_peer_admission import (
    OfflinePeerAdmission,
)
from readonly_connection_review.offline_gateway_step_gate import (
    OfflineGatewayGate,
)
from readonly_connection_review.testnet_egress_policy_review_offline import (
    inspect_synthetic_requests, policy_contract,
)


def review_offline_identity_to_frames(
    connection, *,
    expected_uid, expected_gid, expected_provenance,
    approved_review_lease, test_nonce, policy, clock=None,
):
    """Produce two *synthetic* safe frames only after all offline checks pass.

    Caller controls the expected metadata in this fixture; this function
    must NEVER be used as a real gateway admission path.
    """
    policy_contract(policy)  # Must remain explicitly network_authorized=False.
    kernel_peer = kernel_unix_peer_credentials(connection)
    actual_provenance = read_linux_process_provenance(kernel_peer.pid)
    matches_reviewed_process(actual_provenance, expected_provenance)
    admission = OfflinePeerAdmission(
        expected_uid=expected_uid,
        expected_gid=expected_gid,
        expected_nonce=test_nonce,
    )
    admission.inspect_synthetic_peer(
        kernel_uid=kernel_peer.uid,
        kernel_gid=kernel_peer.gid,
        kernel_pid=kernel_peer.pid,
        approved_review_lease=approved_review_lease,
        nonce=test_nonce,
    )
    gate = OfflineGatewayGate(clock=clock)
    gate.begin_offline_lease(approval=approved_review_lease, test_nonce=test_nonce)
    frames = [
        gate.review_step(nonce=test_nonce, step=1),
        gate.review_step(nonce=test_nonce, step=2),
    ]
    inspect_synthetic_requests(policy, frames)
    if not gate.finished:
        raise AssertionError("synthetic gate not spent")  # offline test invariant
    return frames
