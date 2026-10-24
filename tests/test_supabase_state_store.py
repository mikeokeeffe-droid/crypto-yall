"""Offline contract tests for opt-in Supabase state adapter; no network or trades."""
import os
import unittest
from unittest.mock import patch, Mock
import supabase_state_store as store


class StateAdapterTests(unittest.TestCase):
    def setUp(self):
        store._REVISIONS.clear()
        self.env = patch.dict(os.environ, {
            "SUPABASE_URL": "https://example.invalid",
            "SUPABASE_SERVICE_ROLE_KEY": "test-only-key",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        store._REVISIONS.clear()

    def test_disabled_by_default(self):
        with patch.dict(os.environ, {"SUPABASE_STATE_ENABLED": ""}):
            self.assertFalse(store.enabled())

    @patch("supabase_state_store.requests.get")
    @patch("supabase_state_store.requests.post")
    def test_load_then_cas_save(self, post, get):
        get.return_value = Mock(json=lambda: [{"state": {"a": 1}, "revision": 1}])
        post.return_value = Mock(json=lambda: 2)
        self.assertEqual(store.load("daily"), {"a": 1})
        store.save("daily", {"a": 2})
        self.assertEqual(post.call_args.kwargs["json"]["p_expected_revision"], 1)
        self.assertEqual(store._REVISIONS["daily"], 2)

    @patch("supabase_state_store.requests.post")
    def test_save_without_load_rejected(self, post):
        with self.assertRaises(RuntimeError):
            store.save("intraday", {})
        post.assert_not_called()

    @patch("supabase_state_store.requests.get")
    def test_missing_row_fails_closed(self, get):
        get.return_value = Mock(json=lambda: [])
        with self.assertRaises(RuntimeError):
            store.load("aggressive")

    @patch("supabase_state_store.requests.get")
    @patch("supabase_state_store.requests.post")
    def test_revision_conflict_fails_closed(self, post, get):
        get.return_value = Mock(json=lambda: [{"state": {}, "revision": 1}])
        store.load("aggressive")
        post.return_value.raise_for_status.side_effect = RuntimeError("409 conflict")
        with self.assertRaises(RuntimeError):
            store.save("aggressive", {"x": 1})
        self.assertEqual(store._REVISIONS["aggressive"], 1)

    @patch("supabase_state_store.requests.get")
    def test_invalid_revision_rejected(self, get):
        get.return_value = Mock(json=lambda: [{"state": {}, "revision": "1"}])
        with self.assertRaises(RuntimeError):
            store.load("daily")


if __name__ == "__main__":
    unittest.main()
