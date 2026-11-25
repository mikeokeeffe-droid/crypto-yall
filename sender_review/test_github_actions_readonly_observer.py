"""Offline mocks only: public GitHub workflow visibility, not a heartbeat."""
import datetime as dt
import io
import unittest
from unittest.mock import patch

from sender_review.github_actions_readonly_observer import (
    _ROOT, _WORKFLOWS, _public_fetch, interpret_workflow_response, observe_all,
    assess_dispatch_history_offline, RunObservation,
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

    def test_stale_completed_bot_run_is_history_gap_not_healthy(self):
        for bot, old_date in (
            ("daily", "2026-10-24T00:15:33Z"),
            ("intraday", "2026-11-07T00:16:22Z"),
            ("aggressive", "2026-10-24T13:02:14Z"),
        ):
            with self.subTest(bot=bot):
                seen = interpret_workflow_response(
                    bot, payload(updated_at=old_date), now=NOW
                )
                reviewed = assess_dispatch_history_offline(seen)
                self.assertEqual(reviewed.verdict, "HISTORICAL_DISPATCH_GAP")
                self.assertFalse(reviewed.live_bot_running_verified)
                self.assertFalse(reviewed.open_position_protection_verified)
                self.assertFalse(reviewed.restart_authorized)
                self.assertFalse(reviewed.schedule_authoritatively_verified)

    def test_cancelled_or_failed_run_never_looks_healthy(self):
        for conclusion in ("cancelled", "failure", "timed_out"):
            with self.subTest(conclusion=conclusion):
                observation = interpret_workflow_response(
                    "intraday", payload(conclusion=conclusion), now=NOW
                )
                reviewed = assess_dispatch_history_offline(observation)
                self.assertEqual(
                    reviewed.verdict, "LAST_GITHUB_RUN_NOT_SUCCESSFUL"
                )
                self.assertFalse(reviewed.restart_authorized)
        queued = interpret_workflow_response(
            "daily", payload(status="queued", conclusion=None), now=NOW
        )
        self.assertEqual(
            assess_dispatch_history_offline(queued).verdict,
            "GITHUB_JOB_NOT_COMPLETED",
        )

    def test_recent_success_is_not_server_or_exchange_attestation(self):
        for bot in ("daily", "intraday", "aggressive"):
            recent = interpret_workflow_response(bot, payload(), now=NOW)
            reviewed = assess_dispatch_history_offline(recent)
            self.assertEqual(reviewed.verdict, "RECENT_GITHUB_RUN_ONLY")
            self.assertFalse(reviewed.live_bot_running_verified)
            self.assertFalse(reviewed.open_position_protection_verified)
            self.assertFalse(reviewed.restart_authorized)
        self.assertEqual(
            assess_dispatch_history_offline(
                RunObservation(bot="daily", state="NO_RUNS")
            ).verdict, "NO_GITHUB_RUNS"
        )
        self.assertEqual(
            assess_dispatch_history_offline(
                RunObservation(bot="intraday", state="UNVERIFIED")
            ).verdict, "UNVERIFIED"
        )
        self.assertEqual(
            assess_dispatch_history_offline(object()).verdict, "UNVERIFIED"
        )

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
