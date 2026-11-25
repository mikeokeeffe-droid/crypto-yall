"""Fail-closed offline report freshness / completeness regression."""
import datetime as dt
import json
import unittest

from sender_review.report_snapshot_health_offline import (
    ReportHealthReview, inspect_report_snapshot_offline,
)


NOW = dt.datetime(2026, 11, 20, 16, 0, tzinfo=dt.timezone.utc)
BOTS = ("daily", "intraday", "aggressive")


def fixture():
    return {
        "schema_version": 2,
        "reporting_only": True,
        "date_utc": NOW.date().isoformat(),
        "generated_at": NOW.isoformat(),
        "report_errors": [],
        "bots": {b: {"errors": [], "incomplete_accounting": []} for b in BOTS},
    }


def run(report, *, now=NOW, max_age_seconds=7200):
    payload = json.dumps(report).encode("utf-8")
    return inspect_report_snapshot_offline(
        payload, now=now, max_age_seconds=max_age_seconds,
    )


class ReportSnapshotHealthTests(unittest.TestCase):
    def assert_no_authority(self, reviewed):
        self.assertFalse(reviewed.publishing_approved)
        self.assertFalse(reviewed.trading_approved)
        self.assertFalse(reviewed.live_bots_running_verified)
        self.assertFalse(reviewed.safe_to_modify_main)

    def test_complete_fresh_snapshot_passes_metadata_only(self):
        reviewed = run(fixture())
        self.assertEqual(reviewed.status, "METADATA_PASS")
        self.assertTrue(reviewed.report_metadata_fresh)
        self.assertTrue(reviewed.source_is_complete)
        self.assert_no_authority(reviewed)

    def test_report_staleness_clock_timezone_and_timestamp_mismatch_hold(self):
        for bad in (
            NOW + dt.timedelta(seconds=7201),
            NOW - dt.timedelta(seconds=1),
        ):
            with self.subTest(bad=bad):
                self.assertEqual(run(fixture(), now=bad).status, "HOLD")
        one = fixture()
        one["generated_at"] = "2026-11-20T16:00:00"
        self.assertEqual(run(one).status, "HOLD")
        one = fixture()
        one["date_utc"] = "2026-11-19"
        self.assertEqual(run(one).status, "HOLD")
        self.assertEqual(run(fixture(), max_age_seconds=999999).status, "HOLD")
        self.assertEqual(run(fixture(), max_age_seconds=True).status, "HOLD")
        self.assertEqual(
            inspect_report_snapshot_offline(
                json.dumps(fixture()).encode(), now=NOW.replace(tzinfo=None)
            ).status, "HOLD",
        )

    def test_incomplete_or_error_reports_hold(self):
        for mutation in (
            lambda d: d["bots"].pop("daily"),
            lambda d: d["bots"].update({"unknown_bot": {}}),
            lambda d: d["bots"]["intraday"].update({"errors": ["network down"]}),
            lambda d: d["bots"]["aggressive"].update({"incomplete_accounting": ["gap"]}),
            lambda d: d.update({"report_errors": ["missing Gist"]}),
            lambda d: d.update({"reporting_only": False}),
            lambda d: d.update({"schema_version": True}),
        ):
            data = fixture()
            mutation(data)
            self.assertEqual(run(data).status, "HOLD")
        self.assertEqual(inspect_report_snapshot_offline(b"", now=NOW).status, "HOLD")
        self.assertEqual(inspect_report_snapshot_offline(b"[]" , now=NOW).status, "HOLD")
        self.assertEqual(inspect_report_snapshot_offline(b"x"*1_048_577, now=NOW).status, "HOLD")

    def test_rejects_duplicate_keys_nonfinite_and_does_not_echo_secrets(self):
        data = json.dumps(fixture())
        malicious = (
            b'{"schema_version":2,"schema_version":2}',
            b'{"generated_at":NaN}',
            b'{"generated_at":Infinity}',
            data.replace('"reporting_only": true', '"reporting_only": true, "reporting_only": true').encode(),
            b"\\xff" ,
        )
        for payload in malicious:
            with self.subTest(payload=payload[:50]):
                self.assertEqual(
                    inspect_report_snapshot_offline(payload, now=NOW).status, "HOLD"
                )
        private = fixture()
        private["dangerous_private_field"] = "PRIVATE_KEY_EXAMPLE_DO_NOT_LEAK"
        reviewed = run(private)
        self.assert_no_authority(reviewed)
        self.assertNotIn("PRIVATE_KEY_EXAMPLE_DO_NOT_LEAK", repr(reviewed))


if __name__ == "__main__":
    unittest.main()
