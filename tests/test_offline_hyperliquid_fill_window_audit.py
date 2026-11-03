"""Fake-only boundary tests for Hyperliquid time-window history review."""
import unittest
from offline_hyperliquid_fill_window_audit import audit_fill_windows_offline

ACCOUNT = "0x" + "a" * 40


def fill(tid, timestamp):
    return {"coin": "SOL", "oid": 123, "tid": tid, "time": timestamp,
            "side": "B", "dir": "Open Long", "sz": "1",
            "px": "100", "hash": "0x" + "b" * 64}


def window(lo, hi, fills):
    return dict(start_ms=lo, end_ms=hi, response=fills,
                request={"type": "userFillsByTime", "user": ACCOUNT,
                         "startTime": lo, "endTime": hi,
                         "aggregateByTime": False})


def audit(windows, **kwargs):
    return audit_fill_windows_offline(
        account=ACCOUNT, start_ms=100, end_ms=109,
        windows=windows, **kwargs)


class FillWindowBoundaryTests(unittest.TestCase):
    def test_consecutive_ranges_preserve_same_millisecond_fills(self):
        result = audit([window(100, 104, [fill(1, 104), fill(2, 104)]),
                        window(105, 109, [fill(3, 105)])])
        self.assertEqual(result.status, "parsed_untrusted")
        self.assertEqual(len(result.records), 3)

    def test_empty_windows_cannot_prove_exchange_history(self):
        result = audit([window(100, 109, [])])
        self.assertEqual(result.status, "parsed_untrusted")
        self.assertIn("unverified", result.reason)

    def test_missing_range_or_early_end_holds(self):
        for pages in ([window(100, 104, []), window(106, 109, [])],
                      [window(100, 104, [])],
                      [window(101, 109, [])]):
            with self.subTest(pages=pages):
                self.assertEqual(audit(pages).status, "hold")

    def test_overlap_or_replay_holds(self):
        for pages in ([window(100, 105, []), window(105, 109, [])],
                      [window(100, 109, []), window(100, 109, [])]):
            with self.subTest(pages=pages):
                self.assertEqual(audit(pages).status, "hold")

    def test_saturated_page_holds(self):
        self.assertEqual(audit([window(100, 109, [fill(1, 105)])],
                               cap=1).status, "hold")

    def test_duplicate_trade_id_across_windows_holds(self):
        self.assertEqual(audit([
            window(100, 104, [fill(1, 104)]),
            window(105, 109, [fill(1, 105)]),
        ]).status, "hold")

    def test_same_timestamp_at_boundary_not_skipped(self):
        result = audit([window(100, 104, [fill(1, 104)]),
                        window(105, 109, [fill(2, 105)])])
        self.assertEqual(result.status, "parsed_untrusted")
        self.assertEqual([r[3] for r in result.records], [104, 105])

    def test_out_of_range_and_wrong_account_holds(self):
        wrong = window(100, 109, [fill(1, 110)])
        self.assertEqual(audit([wrong]).status, "hold")
        wrong = window(100, 109, [])
        wrong["request"]["user"] = "0x" + "c" * 40
        self.assertEqual(audit([wrong]).status, "hold")

    def test_max_window_limit_holds(self):
        self.assertEqual(audit([window(100, 104, []),
                                window(105, 109, [])],
                               max_windows=1).status, "hold")


if __name__ == "__main__":
    unittest.main()
