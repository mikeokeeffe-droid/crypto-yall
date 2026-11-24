"""OFFLINE ONLY proposed Unix peer-admission decision for a future Testnet gateway.

This module is NOT an authenticating service: it creates no socket, does not
read SO_PEERCRED, issues no token, and offers zero network or trading authority.

An actual gateway must independently obtain peer credentials from the kernel
on a protected AF_UNIX connection, keep authorization state out of caller
control, bind to a host-reviewed OS identity, and guard against a different
process under the same UID. None of those boundaries is implemented here.
"""
import secrets
from readonly_connection_review.testnet_egress_policy_review_offline import PolicyHold


class OfflinePeerAdmission:
    """Pure decision fixture. A boolean review approval is NOT a credential."""

    def __init__(self, *, expected_uid, expected_gid, expected_nonce):
        if (type(expected_uid) is not int or expected_uid <= 0
                or type(expected_gid) is not int or expected_gid <= 0
                or type(expected_nonce) is not str or len(expected_nonce) != 32
                or any(c not in "0123456789abcdef" for c in expected_nonce)):
            raise PolicyHold("invalid offline review fixture")
        self._uid = expected_uid
        self._gid = expected_gid
        self._nonce = expected_nonce
        self._used = False

    def inspect_synthetic_peer(self, *, kernel_uid, kernel_gid, kernel_pid,
                               approved_review_lease, nonce, claimed_identity=None):
        """Test-only admission; no authority to contact Hyperliquid.

        Integers supplied as kernel_uid/gid/pid in these tests are *fixtures*,
        not real OS attestations. The real gateway MUST obtain them from the
        kernel and must not permit the caller to supply these parameters.
        """
        if self._used:
            raise PolicyHold("synthetic admission already spent")
        self._used = True  # Fail closed; even rejected proposals are not reusable.
        if claimed_identity is not None:
            raise PolicyHold("caller-supplied identity forbidden")
        if (type(kernel_uid) is not int or kernel_uid != self._uid
                or type(kernel_gid) is not int or kernel_gid != self._gid
                or type(kernel_pid) is not int or kernel_pid <= 1):
            raise PolicyHold("synthetic peer identity rejected")
        if (approved_review_lease is not True or type(nonce) is not str
                or not secrets.compare_digest(nonce, self._nonce)):
            raise PolicyHold("synthetic review lease rejected")
        return True  # An offline test result ONLY; never a network permit.
