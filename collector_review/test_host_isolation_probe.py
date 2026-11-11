"""Offline fixtures for kernel-observation review; never probe CI host here."""
from dataclasses import replace
import unittest

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


if __name__ == "__main__":
    unittest.main()
