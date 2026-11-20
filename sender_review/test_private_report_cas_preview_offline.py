"""Offline mock-only concurrent publisher CAS behavior; no publishing."""
import datetime as dt
import hashlib
import json
import unittest

from sender_review.private_report_cas_preview_offline import (
    PrivateReportCasPreview, SimulatedPrivateHead,
    preview_private_report_cas_offline,
)
from sender_review.test_isolated_report_handoff_offline import fixture

UTC = dt.timezone.utc
OLD_TIME = dt.datetime(2026, 11, 20, 14, 0, tzinfo=UTC)
NEW_TIME = dt.datetime(2026, 11, 20, 15, 0, tzinfo=UTC)


def as_bytes(value):
    return json.dumps(value, sort_keys=True).encode("utf-8")


def setup():
    previous = as_bytes(fixture(OLD_TIME))
    candidate = as_bytes(fixture(NEW_TIME))
    head = SimulatedPrivateHead(
        version=9, snapshot_sha256=hashlib.sha256(previous).hexdigest(),
    )
    return previous, candidate, head


def preview(*, current=None, observed=None, previous=None, candidate=None, now=NEW_TIME):
    prior, next_report, head = setup()
    return preview_private_report_cas_offline(
        current_head=head if current is None else current,
        observed_head=head if observed is None else observed,
        previous=prior if previous is None else previous,
        candidate=next_report if candidate is None else candidate,
        now=now,
    )


class PrivateReportCasPreviewTests(unittest.TestCase):
    def never_authorized(self, checked):
        self.assertFalse(checked.report_published)
        self.assertFalse(checked.private_store_verified)
        self.assertFalse(checked.actual_atomicity_verified)
        self.assertFalse(checked.trading_authorized)
        self.assertFalse(checked.may_modify_main)

    def test_one_synthetic_writer_can_preview_but_never_publish(self):
        result = preview()
        self.assertEqual(result.verdict, "CAS_PREVIEW_ONLY_HOLD")
        self.assertEqual(result.proposed_next_head.version, 10)
        self.never_authorized(result)
        self.assertNotIn("closed_trades", repr(result))

    def test_two_writers_same_prior_version_conflict_after_first(self):
        prior, next_report, old = setup()
        first = preview()
        second = preview_private_report_cas_offline(
            current_head=first.proposed_next_head,
            observed_head=old,
            previous=prior,
            candidate=next_report,
            now=NEW_TIME,
        )
        self.assertEqual(second.verdict, "CONFLICT_HOLD")
        self.assertIsNone(second.proposed_next_head)
        self.never_authorized(second)

    def test_old_report_bytes_cannot_claim_new_head(self):
        prior, next_report, old = setup()
        bad = SimulatedPrivateHead(version=9, snapshot_sha256="f" * 64)
        outcome = preview(current=bad, observed=bad)
        self.assertEqual(outcome.verdict, "BASE_DIGEST_MISMATCH_HOLD")
        self.never_authorized(outcome)
        bad = SimulatedPrivateHead(version=9, snapshot_sha256="not-hex")
        self.assertEqual(preview(current=bad, observed=bad).verdict, "HOLD")

    def test_history_rewrite_and_stale_candidate_do_not_advance(self):
        prior, next_report, old = setup()
        tampered = json.loads(next_report)
        tampered["short_opportunity_check"]["tracking_started_at"] = (
            NEW_TIME.isoformat()
        )
        result = preview(candidate=as_bytes(tampered))
        self.assertEqual(result.verdict, "CONTINUITY_HOLD")
        self.assertIsNone(result.proposed_next_head)
        self.never_authorized(result)
        self.assertEqual(
            preview(candidate=prior).verdict, "CONTINUITY_HOLD",
        )

    def test_invalid_inputs_and_counter_limits_never_authorize(self):
        prior, next_report, old = setup()
        invalid = (
            SimulatedPrivateHead(version=True, snapshot_sha256=old.snapshot_sha256),
            SimulatedPrivateHead(version=-1, snapshot_sha256=old.snapshot_sha256),
            SimulatedPrivateHead(version=1_000_000_000, snapshot_sha256=old.snapshot_sha256),
            SimulatedPrivateHead(version=9, snapshot_sha256="A" * 64),
        )
        for head in invalid:
            with self.subTest(head=head.version):
                result = preview(current=head, observed=head)
                self.assertEqual(result.verdict, "HOLD")
                self.never_authorized(result)
        self.assertEqual(
            preview_private_report_cas_offline(
                current_head=old, observed_head=old,
                previous=b"", candidate=next_report, now=NEW_TIME,
            ).verdict,
            "BASE_DIGEST_MISMATCH_HOLD",
        )

    def test_private_contents_are_not_exposed_in_result(self):
        _, _, head = setup()
        private = fixture(NEW_TIME)
        private["secret"] = "DONOTPRINT_PRIVATE_REPORT_PAYLOAD"
        result = preview(candidate=as_bytes(private))
        self.never_authorized(result)
        self.assertNotIn("DONOTPRINT_PRIVATE_REPORT_PAYLOAD", repr(result))
        self.assertNotIn("DONOTPRINT_PRIVATE_REPORT_PAYLOAD", result.reason)


if __name__ == "__main__":
    unittest.main()
