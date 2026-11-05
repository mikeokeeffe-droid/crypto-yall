"""Synthetic dispatch race and crash cases. No exchange calls."""
import unittest
from offline_dispatch_lifecycle_review import review_dispatch_transition as review

class DispatchLifecycleTests(unittest.TestCase):
    def test_pre_send_states_never_grant_dispatch(self):
        for state, event, expected in (
            ("reserved", "prepare", "prepared"),
            ("prepared", "mark_dispatch_unknown", "dispatch_unknown"),
            ("dispatch_unknown", "observed", "observed_unverified"),
        ):
            with self.subTest(state=state):
                result = review(current_state=state, event=event, fence=41, current_fence=41)
                self.assertEqual(result.state, expected)
                self.assertFalse(result.permitted)

    def test_stale_worker_after_fence_reassignment_holds(self):
        result = review(current_state="prepared", event="mark_dispatch_unknown",
                        fence=41, current_fence=42)
        self.assertEqual(result.state, "hold")
        self.assertFalse(result.permitted)

    def test_timeout_or_crash_never_releases_or_retries(self):
        for event in ("timeout", "crash", "retry", "release", "prepare", "mark_dispatch_unknown"):
            with self.subTest(event=event):
                result = review(current_state="dispatch_unknown", event=event,
                                fence=41, current_fence=41)
                self.assertEqual(result.state, "hold")
                self.assertFalse(result.permitted)

    def test_legacy_and_unverified_orders_never_dispatch(self):
        for state in ("legacy", "observed_unverified", "hold", "filled"):
            result = review(current_state=state, event="prepare",
                            fence=41, current_fence=41)
            self.assertFalse(result.permitted)
            self.assertEqual(result.state, "hold")

    def test_invalid_fences_hold(self):
        for old, new in ((True,1),(0,0),(-1,1),(41,42),(41,True)):
            result = review(current_state="reserved", event="prepare",
                            fence=old, current_fence=new)
            self.assertEqual(result.state, "hold")

if __name__ == "__main__":
    unittest.main()
