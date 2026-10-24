"""Offline safety checks for snapshot validation. No network access."""
import unittest
from unittest.mock import Mock, patch
from scripts.backup_gists_to_supabase import canonical, digest, gist_read


class SnapshotTests(unittest.TestCase):
    def test_canonical_equivalent_objects(self):
        self.assertEqual(digest({"b": 2, "a": 1}), digest({"a": 1, "b": 2}))

    def test_invalid_state_rejected(self):
        for bad in (None, [], 5, "state"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    canonical(bad)

    def test_nan_rejected(self):
        with self.assertRaises(ValueError):
            canonical({"bad": float("nan")})

    def test_gist_metadata_version(self):
        session = Mock()
        response = Mock()
        response.json.return_value = {
            "history": [{"version": "abcdef"}],
            "files": {"state.json": {"content": '{"x":1}', "truncated": False}},
        }
        session.get.return_value = response
        state, version = gist_read(session, "id", "state.json", "token")
        self.assertEqual(state, {"x": 1})
        self.assertEqual(version, "abcdef")

    def test_malformed_gist_json(self):
        session = Mock()
        response = Mock()
        response.json.return_value = {
            "history": [{"version": "abcdef"}],
            "files": {"state.json": {"content": "{broken", "truncated": False}},
        }
        session.get.return_value = response
        with self.assertRaises(ValueError):
            gist_read(session, "id", "state.json", "token")

    def test_gist_http_failure(self):
        session = Mock()
        session.get.return_value.raise_for_status.side_effect = RuntimeError("HTTP 403")
        with self.assertRaises(RuntimeError):
            gist_read(session, "id", "state.json", "token")


if __name__ == "__main__":
    unittest.main()
