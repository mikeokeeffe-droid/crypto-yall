"""Offline fixtures for kernel-observation review; never probe CI host here."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from collector_review.host_isolation_probe import (
    HostProbeDecision, review_host_observations_offline,
)

STATUS = """Name:\tpython3
Uid:\t2001\t2001\t2001\t2001
Gid:\t2002\t2002\t2002\t2002
NoNewPrivs:\t1
Seccomp:\t2
CapInh:\t0000000000000000
CapPrm:\t0000000000000000
CapEff:\t0000000000000000
CapBnd:\t0000000000000000
CapAmb:\t0000000000000000
"""
CGROUP = "0::/system.slice/testnet-collector-offline-review.service\n"


def review(**changes):
    args=dict(
        status_text=STATUS,
        cgroup_text=CGROUP,
        process_netns="net:[4026532100]",
        init_netns="net:[4026531993]",
        effective_uid=2001,
        effective_gid=2002,
        environment_names=("LANG", "PATH", "PYTHONDONTWRITEBYTECODE"),
    )
    args.update(changes)
    return review_host_observations_offline(**args)


class HostIsolationProbeTests(unittest.TestCase):
    def test_good_synthetic_kernel_status_still_grants_no_authority(self):
        r=review()
        self.assertEqual(r.state, "host_candidate")
        self.assertTrue(r.kernel_identity_candidate)
        self.assertTrue(r.privilege_restrictions_candidate)
        self.assertTrue(r.separate_network_namespace_candidate)
        self.assertTrue(r.environment_names_candidate)
        self.assertFalse(r.network_egress_verified)
        self.assertFalse(r.secret_file_access_verified)
        self.assertFalse(r.origin_authenticated)
        self.assertFalse(r.trading_authorized)
        self.assertFalse(r.testnet_read_authorized)

    def test_root_or_credential_mismatch_stays_hold(self):
        for name, value in (
            ("effective_uid",0), ("effective_gid",0),
            ("effective_uid",2003),("effective_gid",2003),
            ("effective_uid",True),("effective_gid",False),
            ("status_text", STATUS.replace("2001\t2001\t2001\t2001",
                                           "2001\t2001\t2001\t0")),
            ("status_text", STATUS.replace("2002\t2002\t2002\t2002",
                                           "2002\t2002\t0\t2002")),
        ):
            with self.subTest(field=name, value=str(value)[:60]):
                self.assertEqual(review(**{name:value}).state,"hold")

    def test_missing_kernel_isolation_capabilities_or_cgroup_stays_hold(self):
        cases = (
            {"status_text": STATUS.replace("NoNewPrivs:\t1","NoNewPrivs:\t0")},
            {"status_text": STATUS.replace("Seccomp:\t2","Seccomp:\t0")},
            {"status_text": STATUS.replace("CapEff:\t0000000000000000",
                                            "CapEff:\t0000000000000001")},
            {"status_text": STATUS.replace("CapBnd:\t0000000000000000",
                                            "CapBnd:\t0000000000000001")},
            {"status_text": STATUS + "Uid:\t2001\t2001\t2001\t2001\n"},
            {"cgroup_text": "0::/user.slice/not-collector.service\n"},
            {"process_netns": "net:[4026531993]"},
            {"init_netns": "net:[4026532100]"},
            {"process_netns": "unknown"},
            {"status_text": ""},
        )
        for change in cases:
            with self.subTest(change=str(change)[:80]):
                r=review(**change)
                self.assertEqual(r.state,"hold")
                self.assertFalse(r.testnet_read_authorized)

    def test_environment_name_metadata_rejects_secret_paths(self):
        for names in (
            ("PATH","HL_PRIVATE_KEY"),
            ("PATH","AWS_ACCESS_KEY_ID"),
            ("PATH","HTTP_PROXY"),
            ("PATH","PATH"),
            ("PATH",None),
            "PATH",
        ):
            with self.subTest(names=names):
                self.assertEqual(review(environment_names=names).state,"hold")


    def test_diagnostic_emits_only_bounded_name_fingerprints(self):
        from collector_review.host_isolation_probe import (
            _unexpected_environment_name_fingerprints,
        )
        import hashlib
        names=("PATH", "LANG", "HL_PRIVATE_KEY", "UNEXPECTED_RUNTIME_VAR")
        count, tokens=_unexpected_environment_name_fingerprints(names)
        self.assertEqual(count, 2)
        expected=tuple(hashlib.sha256(
            ("offline-collector-env-v1:" + name).encode()
        ).hexdigest()[:16] for name in sorted(names)
                   if name not in ("PATH","LANG"))
        self.assertEqual(tokens, expected)
        self.assertTrue(all("HL_PRIVATE_KEY" not in x for x in tokens))
        self.assertEqual(_unexpected_environment_name_fingerprints(
            ("PATH", "LANG")), (0, ()))
        many=tuple("UNEXPECTED_" + str(i) for i in range(20))
        count, tokens=_unexpected_environment_name_fingerprints(many)
        self.assertEqual(count, 20)
        self.assertEqual(len(tokens), 8)

    def test_standard_systemd_shell_name_is_allowed_but_unknown_names_hold(self):
        self.assertEqual(
            review(environment_names=("PATH", "LANG", "SHELL")).state,
            "host_candidate",
        )
        self.assertEqual(
            review(environment_names=("PATH", "LANG", "SHELL",
                                      "HL_PRIVATE_KEY")).state,
            "hold",
        )
        self.assertEqual(
            review(environment_names=("PATH", "LANG", "SHELL",
                                      "UNEXPECTED_RUNTIME_VAR")).state,
            "hold",
        )

    def test_permission_denied_with_missing_host_baseline_fails_closed(self):
        def readlink(path):
            if path == "/proc/self/ns/net":
                return "net:[4026532100]"
            raise PermissionError("PID 1 namespace protected")

        with patch("collector_review.host_isolation_probe.os.readlink",
                   side_effect=readlink), patch(
                   "collector_review.host_isolation_probe._read_root_owned_host_netns_reference",
                   return_value=None):
            from collector_review.host_isolation_probe import (
                probe_current_host_without_network,
            )
            decision = probe_current_host_without_network()
        self.assertEqual(decision.state, "hold")
        self.assertFalse(decision.network_egress_verified)
        self.assertFalse(decision.testnet_read_authorized)
        self.assertFalse(decision.trading_authorized)

    def test_supplied_host_baseline_must_be_distinct(self):
        decision = review(init_netns="net:[4026532100]")
        self.assertEqual(decision.state, "hold")
        self.assertFalse(decision.network_egress_verified)


if __name__ == "__main__":
    unittest.main()
