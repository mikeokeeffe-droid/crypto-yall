"""Offline mocks only: public GitHub workflow visibility, not a heartbeat."""
import datetime as dt
import io
import unittest
from unittest.mock import patch

from sender_review.github_actions_readonly_observer import (
    _ROOT, _WORKFLOWS, _public_fetch, interpret_workflow_response, observe_all,
)

NOW = dt.datetime(2026, 11, 19, 12, 0, tzinfo=dt.timezone.utc)


def payload(status="completed", conclusion="success",
            updated_at="2026-11-19T11:58:00Z"):
    return {"workflow_runs": [{
        "status": status,
        "conclusion": conclusion,
        "updated_at": updated_at,
    }]}


class GithubActionsReadonlyObserverTests(unittest.TestCase):
    def test_three_named_bot_workflows_observed_with_no_credentials(self):
        seen = []
        def fake_fetch(url):
            seen.append(url)
            return payload()
        rows = observe_all(fetch=fake_fetch, now=NOW)
        self.assertEqual([r.bot for r in rows], [
            "daily", "intraday", "aggressive"
        ])
        self.assertEqual([r.state for r in rows], ["COMPLETED"] * 3)
        self.assertTrue(all(r.age_minutes == 2 for r in rows))
        self.assertTrue(all("NOT a heartbeat" in r.note for r in rows))
        self.assertEqual(seen, [
            _ROOT + workflow + "/runs?per_page=1"
            for _, workflow in _WORKFLOWS
        ])

    def test_no_runs_means_no_evidence_not_healthy(self):
        row = interpret_workflow_response(
            "daily", {"workflow_runs": []}, now=NOW
        )
        self.assertEqual(row.state, "NO_RUNS")
        self.assertIsNone(row.age_minutes)

    def test_stale_workflow_not_a_live_connection(self):
        row = interpret_workflow_response(
            "intraday", payload(updated_at="2026-10-24T00:00:00Z"),
            now=NOW,
        )
        self.assertGreater(row.age_minutes, 1440)
        self.assertIn("NOT a heartbeat", row.note)

    def test_untrusted_invalid_data_or_unreachable_is_unverified(self):
        def fake_fetch(url):
            if url.endswith("execute-trades.yml/runs?per_page=1"):
                return {"workflow_runs": [{"status": "invented"}]}
            if url.endswith("execute-intraday.yml/runs?per_page=1"):
                raise OSError("offline")
            return {"workflow_runs": "invalid"}
        rows = observe_all(fetch=fake_fetch, now=NOW)
        self.assertEqual([x.state for x in rows], ["UNVERIFIED"] * 3)

    def test_future_time_and_unknown_result_denied(self):
        for bad in (
            payload(updated_at="2026-11-19T12:10:00Z"),
            payload(status="not-a-status"),
            payload(conclusion="TRADING_APPROVED"),
            {"workflow_runs": [1]},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                interpret_workflow_response("daily", bad, now=NOW)

    def test_public_fetch_only_allows_fixed_readonly_workflow_urls(self):
        for bad in (
            "https://api.hyperliquid.xyz/exchange",
            "https://api.github.com/user",
            _ROOT + "execute-trades.yml/dispatches",
            _ROOT + "execute-trades.yml/runs?per_page=1000",
        ):
            with self.subTest(url=bad), self.assertRaises(ValueError):
                _public_fetch(bad)

    def test_network_is_not_invoked_when_mocked(self):
        with patch(
            "sender_review.github_actions_readonly_observer."
            "urllib.request.urlopen",
            side_effect=AssertionError("must remain offline"),
        ):
            rows = observe_all(fetch=lambda _: payload(), now=NOW)
        self.assertEqual(len(rows), 3)


if __name__ == "__main__":
    unittest.main()
