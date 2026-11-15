"""Offline, inert outage-exposure triage tests; no real protection claims."""
import ast
from dataclasses import replace
from pathlib import Path
import unittest

from sender_review.outage_exposure_triage_offline import (
    SyntheticOutageIncident, review_outage_exposure_fixture_offline,
)


def incident(**updates):
    case = SyntheticOutageIncident(
        event="sender_unavailable",
        exposure="open",
        protection="unknown",
        history_complete=False,
        on_call_acknowledged=False,
        alert_paths_tested=False,
        unresolved_attempt=True,
        original_writers_revoked=True,
        single_writer_verified=True,
    )
    return replace(case, **updates)


class OutageExposureTriageOfflineTests(unittest.TestCase):
    def assert_never_authorized(self, response):
        self.assertEqual(response.state, "NO_GO")
        self.assertTrue(response.stop_new_entries)
        self.assertTrue(response.stop_new_pyramids)
        self.assertTrue(response.retain_unknown_attempt_fences)
        self.assertTrue(response.human_response_required)
        for name in (
            "real_position_verified", "protective_coverage_verified",
            "runtime_alert_delivered", "operator_ack_verified",
            "fence_released", "retry_authorized", "close_authorized",
            "rollback_authorized", "trade_authorized", "signing_enabled",
        ):
            self.assertIs(getattr(response, name), False, name)

    def test_outage_with_open_or_unknown_exposure_is_critical(self):
        for event in (
            "sender_unavailable", "collector_unavailable",
            "protective_close_failed", "unknown_ack", "partial_fill",
        ):
            for exposure in ("open", "unknown"):
                with self.subTest(event=event, exposure=exposure):
                    result = review_outage_exposure_fixture_offline(
                        incident(event=event, exposure=exposure)
                    )
                    self.assertTrue(result.fixture_coherent)
                    self.assertEqual(result.severity, "CRITICAL")
                    self.assertTrue(result.emergency_rescue_required)
                    self.assert_never_authorized(result)

    def test_flat_claim_does_not_override_unknown_ack_or_failed_close(self):
        for event in ("unknown_ack", "protective_close_failed"):
            result = review_outage_exposure_fixture_offline(
                incident(event=event, exposure="flat",
                         protection="reported_healthy")
            )
            self.assertEqual(result.severity, "CRITICAL")
            self.assert_never_authorized(result)

    def test_reported_healthy_is_not_verified_protection(self):
        result = review_outage_exposure_fixture_offline(incident(
            event="rollback_requested", exposure="flat",
            protection="reported_healthy", unresolved_attempt=False,
            history_complete=True, alert_paths_tested=True,
            on_call_acknowledged=True
        ))
        self.assertEqual(result.severity, "REVIEW_REQUIRED")
        self.assertFalse(result.emergency_rescue_required)
        self.assertTrue(result.fixture_coherent)
        self.assert_never_authorized(result)

    def test_old_writers_and_missing_alert_coverage_never_approve_cutover(self):
        for changes in (
            {"original_writers_revoked": False},
            {"single_writer_verified": False},
            {"alert_paths_tested": False},
            {"on_call_acknowledged": False},
        ):
            with self.subTest(changes=changes):
                result = review_outage_exposure_fixture_offline(
                    incident(event="rollback_requested",
                             unresolved_attempt=False, **changes)
                )
                self.assertEqual(result.severity, "CRITICAL")
                self.assert_never_authorized(result)

    def test_invalid_fixtures_fail_closed(self):
        for bad in (
            None, {}, True, "sender_unavailable",
            incident(event="not_a_known_event"),
            incident(exposure="claim_flat_and_safe"),
            incident(protection="safely_closed"),
            incident(history_complete=1),
            incident(on_call_acknowledged=None),
            incident(single_writer_verified="yes"),
        ):
            with self.subTest(bad=bad):
                result = review_outage_exposure_fixture_offline(bad)
                self.assertFalse(result.fixture_coherent)
                self.assertEqual(result.severity, "CRITICAL")
                self.assert_never_authorized(result)

    def test_source_imports_only_stdlib_and_never_connects(self):
        source = Path(__file__).with_name(
            "outage_exposure_triage_offline.py"
        ).read_text("utf-8")
        imports = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imports.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module)
        self.assertEqual(imports, {"dataclasses"})


if __name__ == "__main__":
    unittest.main()
