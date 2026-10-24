"""Offline failure-mode tests for the draft backup workflow; never touches live services."""
import os
import unittest
from unittest.mock import Mock, patch
import requests
from scripts import backup_gists_to_supabase as backup


class FailureModeTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "SNAPSHOT_WINDOW_CONFIRMED": "YES",
            "SUPABASE_URL": "https://example.invalid",
            "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_test",
            "GIST_TOKEN": "test",
            "AGGRESSIVE_GIST_ID": "a",
            "INTRADAY_GIST_ID": "i",
            "GIST_ID": "d",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_post_timeout_reconciles_matching_row(self):
        session = Mock()
        session.post.side_effect = requests.Timeout()
        session.patch.return_value.json.return_value = [{"verified": True}]
        with patch.object(backup.requests, "Session", return_value=session), \
             patch.object(backup, "gist_read", return_value=({"x": 1}, "v1")), \
             patch.object(backup, "read_snapshot", side_effect=lambda s,b,h,i: {
                 "state": {"x": 1}, "verified": False
             }):
            backup.main()
        self.assertEqual(session.patch.call_count, 3)

    def test_post_timeout_mismatched_row_fails_closed(self):
        session = Mock()
        session.post.side_effect = requests.Timeout()
        with patch.object(backup.requests, "Session", return_value=session), \
             patch.object(backup, "gist_read", return_value=({"x": 1}, "v1")), \
             patch.object(backup, "read_snapshot", return_value={
                 "state": {"x": 2}, "verified": False
             }):
            with self.assertRaises(RuntimeError):
                backup.main()
        session.patch.assert_not_called()

    def test_changed_gist_fails_before_verification(self):
        session = Mock()
        with patch.object(backup.requests, "Session", return_value=session), \
             patch.object(backup, "gist_read", side_effect=[
                 ({"x": 1}, "v1"), ({"x": 2}, "v2")
             ]), \
             patch.object(backup, "read_snapshot", return_value={
                 "state": {"x": 1}, "verified": False
             }):
            with self.assertRaises(RuntimeError):
                backup.main()
        session.patch.assert_not_called()

    @unittest.expectedFailure
    def test_patch_timeout_reconciles_verified_row(self):
        """Known blocker: PATCH timeout currently raises without readback."""
        session = Mock()
        session.patch.side_effect = requests.Timeout()
        with patch.object(backup.requests, "Session", return_value=session), \
             patch.object(backup, "gist_read", return_value=({"x": 1}, "v1")), \
             patch.object(backup, "read_snapshot", side_effect=lambda s,b,h,i: {
                 "state": {"x": 1}, "verified": session.patch.called
             }):
            backup.main()


if __name__ == "__main__":
    unittest.main()
