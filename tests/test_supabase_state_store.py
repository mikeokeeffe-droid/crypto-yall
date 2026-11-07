"""Offline contract tests for opt-in Supabase state persistence."""
import os
import unittest
from unittest.mock import Mock, patch

import requests

import supabase_state_store as store


class StateAdapterTests(unittest.TestCase):
    def setUp(self):
        store._REVISIONS.clear()
        self.env = patch.dict(os.environ, {
            "SUPABASE_URL": "https://example.invalid",
            "SUPABASE_SERVICE_ROLE_KEY": "test-only-key",
            "SUPABASE_STATE_ENABLED": "",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        store._REVISIONS.clear()

    def test_disabled_by_default(self):
        self.assertFalse(store.enabled())
        with patch.dict(os.environ, {"SUPABASE_STATE_ENABLED": "on"}):
            self.assertTrue(store.enabled())

    def test_http_url_is_rejected_before_credentials_are_used(self):
        for operation in ("load", "save"):
            with self.subTest(operation=operation):
                with patch.dict(os.environ, {"SUPABASE_URL": "http://example.invalid"}):
                    with patch("supabase_state_store.requests.get") as get, \
                            patch("supabase_state_store.requests.post") as post:
                        if operation == "save":
                            store._REVISIONS["daily"] = 1
                        with self.assertRaisesRegex(ValueError, "HTTPS"):
                            getattr(store, operation)("daily", {}) if operation == "save" else store.load("daily")
                        get.assert_not_called()
                        post.assert_not_called()
                        store._REVISIONS.pop("daily", None)

    @patch("supabase_state_store.requests.get")
    @patch("supabase_state_store.requests.post")
    def test_load_then_cas_save(self, post, get):
        get.return_value = Mock(status_code=200, json=lambda: [{"state": {"a": 1}, "revision": 1}])
        post.return_value = Mock(status_code=200, json=lambda: 2)
        self.assertEqual(store.load("daily"), {"a": 1})
        store.save("daily", {"a": 2})
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
        self.assertFalse(post.call_args.kwargs["allow_redirects"])
        self.assertEqual(post.call_args.kwargs["json"]["p_expected_revision"], 1)
        self.assertEqual(store._REVISIONS["daily"], 2)

    @patch("supabase_state_store.requests.get")
    def test_load_redirect_is_rejected_without_follow_up_request(self, get):
        get.return_value = Mock(status_code=302, headers={"Location": "https://redirect.invalid/"})
        with self.assertRaisesRegex(RuntimeError, "redirects"):
            store.load("daily")
        self.assertEqual(get.call_count, 1)
        self.assertFalse(get.call_args.kwargs["allow_redirects"])

    @patch("supabase_state_store.requests.post")
    def test_save_redirect_is_rejected_without_follow_up_request(self, post):
        store._REVISIONS["daily"] = 1
        post.return_value = Mock(status_code=307, headers={"Location": "https://redirect.invalid/"})
        with self.assertRaisesRegex(RuntimeError, "redirects"):
            store.save("daily", {"a": 2})
        self.assertEqual(post.call_count, 1)
        self.assertFalse(post.call_args.kwargs["allow_redirects"])
        self.assertEqual(store._REVISIONS["daily"], 1)

    @patch("supabase_state_store.requests.post")
    def test_save_without_load_rejected(self, post):
        with self.assertRaises(RuntimeError):
            store.save("intraday", {})
        post.assert_not_called()

    @patch("supabase_state_store.requests.get")
    def test_missing_row_fails_closed(self, get):
        get.return_value = Mock(status_code=200, json=lambda: [])
        with self.assertRaises(RuntimeError):
            store.load("aggressive")

    @patch("supabase_state_store.requests.get")
    @patch("supabase_state_store.requests.post")
    def test_revision_conflict_fails_closed(self, post, get):
        get.return_value = Mock(status_code=200, json=lambda: [{"state": {}, "revision": 1}])
        store.load("aggressive")
        post.return_value.status_code = 200
        post.return_value.raise_for_status.side_effect = RuntimeError("409 conflict")
        with self.assertRaises(RuntimeError):
            store.save("aggressive", {"x": 1})
        self.assertEqual(store._REVISIONS["aggressive"], 1)

    @patch("supabase_state_store.requests.get")
    def test_invalid_revision_rejected(self, get):
        get.return_value = Mock(status_code=200, json=lambda: [{"state": {}, "revision": "1"}])
        with self.assertRaises(RuntimeError):
            store.load("daily")

    @patch("supabase_state_store.requests.get")
    @patch("supabase_state_store.requests.post")
    def test_timeout_does_not_advance_revision_or_retry(self, post, get):
        get.return_value = Mock(status_code=200, json=lambda: [{"state": {}, "revision": 7}])
        store.load("daily")
        post.side_effect = requests.Timeout("uncertain write outcome")
        with self.assertRaises(requests.Timeout):
            store.save("daily", {"x": 1})
        self.assertEqual(store._REVISIONS["daily"], 7)
        self.assertEqual(post.call_count, 1)

    @patch("supabase_state_store.requests.get")
    @patch("supabase_state_store.requests.post")
    def test_restart_requires_fresh_load_before_save(self, post, get):
        get.return_value = Mock(status_code=200, json=lambda: [{"state": {}, "revision": 4}])
        store.load("intraday")
        store._REVISIONS.clear()
        with self.assertRaises(RuntimeError):
            store.save("intraday", {"x": 1})
        post.assert_not_called()

    @patch("supabase_state_store.requests.get")
    def test_read_timeout_fails_closed(self, get):
        get.side_effect = requests.Timeout("read timeout")
        with self.assertRaises(requests.Timeout):
            store.load("aggressive")
        self.assertNotIn("aggressive", store._REVISIONS)


if __name__ == "__main__":
    unittest.main()