"""Keep PR #40 release status fail-closed regardless of offline CI success."""
import unittest
from pathlib import Path
from offline_pr40_release_readiness_ci import (
    BOT_FILES, format_pr40_gate_summary, review_pr40_release_readiness,
)

ROOT=Path(__file__).resolve().parents[1]


def actual_sources():
    return {path:(ROOT/path).read_text(encoding="utf-8")
            for path in BOT_FILES.values()}


class ReleaseReadinessTests(unittest.TestCase):
    def test_all_actual_originals_report_no_go_and_open_risks(self):
        result=review_pr40_release_readiness(actual_sources())
        self.assertEqual(result["decision"],"LIVE NO-GO")
        self.assertFalse(result["trading_authorized"])
        self.assertTrue(result["source_verified"])
        for bot in BOT_FILES:
            finding=result["details"][bot]
            self.assertEqual(finding["direct_mutations"],4)
            self.assertEqual(finding["unsized_closes"],1)
            self.assertGreaterEqual(finding["get_client_calls"],1)
        self.assertTrue(result["details"]["Daily"]["has_key_reference"])
        summary=format_pr40_gate_summary(result)
        self.assertIn("LIVE NO-GO",summary)
        self.assertIn("independent security/risk approval",summary)

    def test_removed_or_malformed_sources_still_no_go(self):
        sources=actual_sources()
        changes=[
            {},
            {**sources,"aggressive_executor.py":"not valid python ?"},
            {**sources,"hyperliquid_executor.py":""},
            {**sources,"intraday_executor.py":"x = 3"},
            {**sources,"extra.py":"unexpected"},
        ]
        for variant in changes:
            with self.subTest(keys=sorted(variant)):
                result=review_pr40_release_readiness(variant)
                self.assertEqual(result["decision"],"LIVE NO-GO")
                self.assertFalse(result["trading_authorized"])
                self.assertFalse(result["source_verified"])
                self.assertIn("LIVE NO-GO",format_pr40_gate_summary(result))

    def test_no_original_modules_loaded(self):
        import sys
        for name in ("hyperliquid_executor","intraday_executor",
                     "aggressive_executor","hyperliquid.exchange"):
            self.assertNotIn(name,sys.modules)


if __name__=="__main__":
    unittest.main()
