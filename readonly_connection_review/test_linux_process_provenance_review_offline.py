"""Offline /proc provenance tests; read only our own process, never start services."""
import os
import unittest

from readonly_connection_review.linux_process_provenance_review_offline import (
    ProcessProvenance, matches_reviewed_process, parse_cgroup_v2,
    parse_proc_stat_start_ticks, read_linux_process_provenance,
)
from readonly_connection_review.testnet_egress_policy_review_offline import PolicyHold


def fake_stat(pid, name="python (worker)"):
    # Field 3..22, with the 20th item being field 22 (starttime).
    fields = ["S"] + ["0"] * 18 + ["12345"]
    return f"{pid} ({name}) " + " ".join(fields) + "\n"


class LinuxProcessProvenanceOfflineTests(unittest.TestCase):
    def test_start_ticks_parser_with_spaced_parentheses(self):
        self.assertEqual(parse_proc_stat_start_ticks(fake_stat(1234), 1234), 12345)

    def test_start_ticks_fail_closed(self):
        for data, pid in (
            ("", 1234),
            (fake_stat(222), 1234),
            ("1234 (broken", 1234),
            ("1234 (x) S 1 2", 1234),
            (fake_stat(1234).replace("12345", "0"), 1234),
            (fake_stat(1234), True),
        ):
            with self.subTest(pid=pid, data=data[:30]), self.assertRaises(PolicyHold):
                parse_proc_stat_start_ticks(data, pid)

    def test_unique_cgroup_v2_membership(self):
        self.assertEqual(parse_cgroup_v2("0::/system.slice/checker.service\n"),
                         "/system.slice/checker.service")
        for data in ("", "1:name=/foo\n", "0::relative\n",
                     "0::/ok\n0::/other\n", "0::/../escape\n", "0::/\x00\n"):
            with self.subTest(data=repr(data)), self.assertRaises(PolicyHold):
                parse_cgroup_v2(data)

    @unittest.skipUnless(os.name == "posix" and os.path.exists("/proc/self/stat"),
                         "Linux procfs required")
    def test_read_only_self_process(self):
        prov = read_linux_process_provenance(os.getpid())
        self.assertEqual(prov.pid, os.getpid())
        self.assertGreater(prov.start_ticks, 0)
        self.assertTrue(prov.cgroup_v2.startswith("/"))
        self.assertTrue(prov.executable.startswith("/"))
        self.assertTrue(matches_reviewed_process(prov, prov))

    def test_provenance_mismatch_denied(self):
        expected = ProcessProvenance(1001, 12345, "/system.slice/review.service",
                                     "/usr/bin/python3")
        for changed in (
            expected._replace(pid=1002),
            expected._replace(start_ticks=12346),
            expected._replace(cgroup_v2="/user.slice"),
            expected._replace(executable="/tmp/python3"),
            expected._replace(start_ticks=True),
            {"pid": 1001},
        ):
            with self.subTest(changed=changed), self.assertRaises(PolicyHold):
                matches_reviewed_process(changed, expected)

    def test_nonexistent_process_fails_closed(self):
        with self.assertRaises(PolicyHold):
            read_linux_process_provenance(2**30)


if __name__ == "__main__":
    unittest.main()
