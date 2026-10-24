"""Offline concurrency and state-preservation tests; never connects to live systems."""
import copy
import unittest


class Conflict(Exception):
    pass


class MemoryState:
    def __init__(self, state):
        self.state = copy.deepcopy(state)
        self.revision = 1
        self.backups = {}

    def read(self):
        return self.revision, copy.deepcopy(self.state)

    def write(self, expected_revision, state):
        if expected_revision != self.revision:
            raise Conflict("stale revision")
        self.backups[self.revision] = copy.deepcopy(self.state)
        self.revision += 1
        self.state = copy.deepcopy(state)
        return self.revision


class StateSafetyTests(unittest.TestCase):
    def setUp(self):
        self.db = MemoryState({
            "positions": {"SOL": {"side": "long", "size": 1}},
            "pending_claims": ["SOL"],
            "peak_returns": {"SOL": 3.2},
            "lock": {"SOL": True},
        })

    def test_stale_writer_does_not_overwrite_protection(self):
        a_rev, a = self.db.read()
        b_rev, b = self.db.read()
        a["peak_returns"]["SOL"] = 4.1
        self.db.write(a_rev, a)
        b["lock"]["SOL"] = False
        with self.assertRaises(Conflict):
            self.db.write(b_rev, b)
        self.assertEqual(self.db.state["peak_returns"]["SOL"], 4.1)
        self.assertTrue(self.db.state["lock"]["SOL"])

    def test_backups_preserve_original_fields(self):
        rev, state = self.db.read()
        original = copy.deepcopy(state)
        state["positions"]["SOL"]["size"] = 2
        self.db.write(rev, state)
        self.assertEqual(self.db.backups[rev], original)

    def test_failed_write_does_not_advance_revision(self):
        rev, state = self.db.read()
        with self.assertRaises(Conflict):
            self.db.write(rev + 1, state)
        self.assertEqual(self.db.revision, rev)
        self.assertEqual(self.db.backups, {})


if __name__ == "__main__":
    unittest.main()
