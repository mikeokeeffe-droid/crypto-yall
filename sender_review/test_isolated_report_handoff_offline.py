"""Offline-only report handoff continuity: no private bytes leave the function."""
import copy
import datetime as dt
import json
import unittest
from sender_review.isolated_report_handoff_offline import (
    review_private_report_handoff_offline,
)

UTC = dt.timezone.utc
PREV = dt.datetime(2026, 11, 20, 14, 0, tzinfo=UTC)
NOW = dt.datetime(2026, 11, 20, 15, 0, tzinfo=UTC)
START = dt.datetime(2026, 11, 7, 0, 0, tzinfo=UTC)
BOTS = ("daily", "intraday", "aggressive")


def fixture(stamp):
    return {
        "schema_version": 2,
        "reporting_only": True,
        "date_utc": stamp.date().isoformat(),
        "generated_at": stamp.isoformat(),
        "report_errors": [],
        "bots": {b: {"errors": [], "incomplete_accounting": []} for b in BOTS},
        "short_opportunity_check": {
            "tracking_started_at": START.isoformat(),
            "updated_at": stamp.isoformat(),
            "bots": {"intraday": {"closed_trades": []}, "aggressive": {"closed_trades": []}},
            "dual_short_confirmed_filter": {
                "bots": {"intraday": {"closed_trades": []}, "aggressive": {"closed_trades": []}},
            },
        },
    }


def encode(data):
    return json.dumps(data, sort_keys=True).encode("utf-8")


class PrivateReportHandoffTests(unittest.TestCase):
    def review(self, before=None, after=None):
        return review_private_report_handoff_offline(
            previous=encode(fixture(PREV) if before is None else before),
            candidate=encode(fixture(NOW) if after is None else after),
            now=NOW,
        )

    def assert_never_authorized(self, result):
        self.assertFalse(result.history_continuity_verified)
        self.assertFalse(result.private_destination_verified)
        self.assertFalse(result.publishing_authorized)
        self.assertFalse(result.trading_authorized)
        self.assertFalse(result.source_workspace_unmodified_proven)

    def test_only_continuity_metadata_can_pass_without_publication_authority(self):
        result = self.review()
        self.assertEqual(result.verdict, "CONTINUITY_METADATA_ONLY_HOLD")
        self.assertTrue(result.metadata_current)
        self.assert_never_authorized(result)

    def test_missing_old_snapshot_cannot_silently_restart_shadow_history(self):
        self.assertEqual(
            review_private_report_handoff_offline(
                previous=b"", candidate=encode(fixture(NOW)), now=NOW,
            ).verdict, "HOLD"
        )
        before = fixture(PREV)
        before.pop("short_opportunity_check")
        self.assertEqual(self.review(before=before).verdict, "HOLD")
        candidate = fixture(NOW)
        candidate["short_opportunity_check"]["tracking_started_at"] = NOW.isoformat()
        self.assertEqual(self.review(after=candidate).verdict, "HOLD")

    def test_stale_or_replayed_report_is_rejected(self):
        same = fixture(NOW)
        self.assertEqual(self.review(before=same, after=same).verdict, "HOLD")
        stale = fixture(NOW)
        stale["generated_at"] = PREV.isoformat()
        self.assertEqual(self.review(after=stale).verdict, "HOLD")
        future = fixture(NOW)
        future["short_opportunity_check"]["updated_at"] = (
            NOW + dt.timedelta(minutes=1)
        ).isoformat()
        self.assertEqual(self.review(after=future).verdict, "HOLD")

    def test_missing_cohort_or_old_updates_rejected(self):
        after = fixture(NOW)
        after["short_opportunity_check"]["bots"].pop("intraday")
        self.assertEqual(self.review(after=after).verdict, "HOLD")
        after = fixture(NOW)
        after["short_opportunity_check"]["dual_short_confirmed_filter"]["bots"].pop("aggressive")
        self.assertEqual(self.review(after=after).verdict, "HOLD")
        after = fixture(NOW)
        after["short_opportunity_check"]["updated_at"] = PREV.isoformat()
        self.assertEqual(self.review(after=after).verdict, "HOLD")

    def test_unexplained_closed_trade_loss_or_rewrite_is_held(self):
        for cohort in ("bots", "dual_short_confirmed_filter"):
            with self.subTest(cohort=cohort):
                before = fixture(PREV)
                after = fixture(NOW)
                prior = (before["short_opportunity_check"][cohort]
                         if cohort == "bots" else
                         before["short_opportunity_check"][cohort])
                following = (after["short_opportunity_check"][cohort]
                             if cohort == "bots" else
                             after["short_opportunity_check"][cohort])
                prior["bots"]["intraday"]["closed_trades"] = [{"id": 1}]
                self.assertEqual(self.review(before=before, after=after).verdict, "HOLD")
                following["bots"]["intraday"]["closed_trades"] = [{"id": 1}]
                self.assertEqual(
                    self.review(before=before, after=after).verdict,
                    "CONTINUITY_METADATA_ONLY_HOLD",
                )
                following["bots"]["intraday"]["closed_trades"] = [{"id": 2}]
                self.assertEqual(self.review(before=before, after=after).verdict, "HOLD")
                following["bots"]["intraday"]["closed_trades"] = [{"id": 1}, {"id": 2}]
                self.assertEqual(
                    self.review(before=before, after=after).verdict,
                    "CONTINUITY_METADATA_ONLY_HOLD",
                )

    def test_200_row_retention_needs_overlapping_tail(self):
        before = fixture(PREV)
        after = fixture(NOW)
        prior = before["short_opportunity_check"]["bots"]["aggressive"]
        following = after["short_opportunity_check"]["bots"]["aggressive"]
        prior["closed_trades"] = [{"id": i} for i in range(200)]
        following["closed_trades"] = [{"id": i} for i in range(1, 201)]
        result = self.review(before=before, after=after)
        self.assertEqual(result.verdict, "CONTINUITY_METADATA_ONLY_HOLD")
        self.assert_never_authorized(result)
        following["closed_trades"] = [{"id": i} for i in range(200, 400)]
        self.assertEqual(self.review(before=before, after=after).verdict, "HOLD")
        following["closed_trades"] = [{"id": i} for i in range(1, 199)]
        self.assertEqual(self.review(before=before, after=after).verdict, "HOLD")
        following["closed_trades"] = [{"id": i} for i in range(201)]
        self.assertEqual(self.review(before=before, after=after).verdict, "HOLD")

    def test_non_dictionary_closed_trades_cannot_pass_handoff(self):
        for bad in (None, {}, "not a list", [1], [{"id": i} for i in range(201)]):
            after = fixture(NOW)
            after["short_opportunity_check"]["bots"]["intraday"]["closed_trades"] = bad
            self.assertEqual(self.review(after=after).verdict, "HOLD")

    def test_malformed_overlarge_and_secret_payloads_are_never_returned(self):
        for previous, candidate in (
            (b"{}", encode(fixture(NOW))),
            (b'{"generated_at":NaN}', encode(fixture(NOW))),
            (encode(fixture(PREV)), b"x" * 1_048_577),
            (b'{"generated_at":1,"generated_at":2}', encode(fixture(NOW))),
        ):
            with self.subTest(sample=previous[:16]):
                value = review_private_report_handoff_offline(
                    previous=previous, candidate=candidate, now=NOW
                )
                self.assertEqual(value.verdict, "HOLD")
                self.assert_never_authorized(value)
        before, after = fixture(PREV), fixture(NOW)
        after["secret"] = "PRIVATE_TRADING_DATA_DO_NOT_EXPORT"
        result = self.review(before=before, after=after)
        self.assert_never_authorized(result)
        self.assertNotIn("PRIVATE_TRADING_DATA_DO_NOT_EXPORT", repr(result))


if __name__ == "__main__":
    unittest.main()
