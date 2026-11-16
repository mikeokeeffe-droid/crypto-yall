"""Pure SHA-1 Git-blob baseline drift checks on known legacy sources."""
from pathlib import Path
import tempfile
import unittest

from sender_review.legacy_exact_source_pin_offline import (
    EXPECTED_GIT_BLOBS, inspect_legacy_source_bytes_offline, _git_blob_sha1,
)
from sender_review.legacy_cutover_audit import ROOT


class LegacyExactSourcePinTests(unittest.TestCase):
    def assert_never_authorized(self, reviewed):
        self.assertEqual(reviewed.state, "NO_GO")
        for key in (
            "executable_cutover_ready", "runtime_source_attested",
            "signer_free_workers_proven", "safe_close_proven",
            "deployment_authorized",
        ):
            self.assertIs(getattr(reviewed, key), False, key)

    def test_all_eight_original_sources_match_commit_baseline_only(self):
        outcome = inspect_legacy_source_bytes_offline()
        self.assert_never_authorized(outcome)
        self.assertTrue(outcome.exact_bytes_match, outcome.changed_or_missing_paths)
        self.assertEqual(len(outcome.matched_paths), 8)
        self.assertEqual(outcome.changed_or_missing_paths, ())
        self.assertEqual(set(outcome.matched_paths), set(EXPECTED_GIT_BLOBS))

    def test_strategy_and_protection_edits_are_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative in EXPECTED_GIT_BLOBS:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((ROOT / relative).read_bytes())
            self.assertTrue(inspect_legacy_source_bytes_offline(root).exact_bytes_match, inspect_legacy_source_bytes_offline(root).changed_or_missing_paths)
            for relative in EXPECTED_GIT_BLOBS:
                target = root / relative
                original = target.read_bytes()
                target.write_bytes(original + b"\n# simulated drift\n")
                result = inspect_legacy_source_bytes_offline(root)
                self.assert_never_authorized(result)
                self.assertFalse(result.exact_bytes_match)
                self.assertIn(relative, result.changed_or_missing_paths)
                target.write_bytes(original)

    def test_missing_symlink_and_unexpected_root_never_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assert_never_authorized(inspect_legacy_source_bytes_offline(root))
            self.assertFalse(inspect_legacy_source_bytes_offline(root).exact_bytes_match)
            self.assert_never_authorized(inspect_legacy_source_bytes_offline("bad"))
        self.assertNotEqual(_git_blob_sha1(b"hello"), _git_blob_sha1(b"hello!"))


if __name__ == "__main__":
    unittest.main()
