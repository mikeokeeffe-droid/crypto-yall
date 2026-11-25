"""Offline-only synthetic peer-admission tests. No real OS peer attestation."""
import unittest
from readonly_connection_review.offline_gateway_peer_admission import OfflinePeerAdmission
from readonly_connection_review.testnet_egress_policy_review_offline import PolicyHold

NONCE = "0123456789abcdef0123456789abcdef"
UID, GID, PID = 995, 982, 1234


def fresh():
    return OfflinePeerAdmission(expected_uid=UID, expected_gid=GID, expected_nonce=NONCE)


def attempt(gate, **overrides):
    args = dict(kernel_uid=UID, kernel_gid=GID, kernel_pid=PID,
                approved_review_lease=True, nonce=NONCE)
    args.update(overrides)
    return gate.inspect_synthetic_peer(**args)


class OfflinePeerAdmissionTests(unittest.TestCase):
    def test_one_synthetic_identity_admitted_only_once(self):
        gate = fresh()
        self.assertTrue(attempt(gate))
        with self.assertRaises(PolicyHold):
            attempt(gate)

    def test_wrong_or_missing_identity_is_denied(self):
        for name, values in {
            "kernel_uid": (0, 1000, True, "995", -1),
            "kernel_gid": (0, 1000, True, "982", -1),
            "kernel_pid": (0, 1, True, "1234", -1),
        }.items():
            for value in values:
                with self.subTest(field=name, value=value), self.assertRaises(PolicyHold):
                    attempt(fresh(), **{name: value})

    def test_denies_unapproved_or_invalid_review_lease(self):
        for approval in (False, None, 1, "yes"):
            with self.subTest(approval=approval), self.assertRaises(PolicyHold):
                attempt(fresh(), approved_review_lease=approval)
        for nonce in ("0" * 32, "", NONCE.upper(), None, 5):
            with self.subTest(nonce=nonce), self.assertRaises(PolicyHold):
                attempt(fresh(), nonce=nonce)

    def test_caller_claim_is_rejected_even_if_it_matches(self):
        for claim in ({"uid": UID}, {"uid": 0}, "", "readonlycheck"):
            with self.subTest(claim=claim), self.assertRaises(PolicyHold):
                attempt(fresh(), claimed_identity=claim)

    def test_denial_consumes_fixture(self):
        gate = fresh()
        with self.assertRaises(PolicyHold):
            attempt(gate, kernel_uid=0)
        with self.assertRaises(PolicyHold):
            attempt(gate)

    def test_invalid_expected_identity_or_nonce_rejected(self):
        for invalid in (
            dict(expected_uid=0),
            dict(expected_gid=0),
            dict(expected_uid=True),
            dict(expected_gid=True),
            dict(expected_nonce="0" * 31),
            dict(expected_nonce="not-hex-not-hex-not-hex-not-hex-!"),
        ):
            args = dict(expected_uid=UID, expected_gid=GID, expected_nonce=NONCE)
            args.update(invalid)
            with self.subTest(invalid=invalid), self.assertRaises(PolicyHold):
                OfflinePeerAdmission(**args)


if __name__ == "__main__":
    unittest.main()
