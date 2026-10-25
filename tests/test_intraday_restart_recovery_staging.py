import unittest
from intraday_restart_recovery_staging import classify_restart

class RestartTests(unittest.TestCase):
    def test_unresolved_intents_never_retry(self):
        for status in ("pending", "submitted", "uncertain", "filled"):
            with self.subTest(status=status):
                self.assertEqual(classify_restart(status, False, True, True, True).action, "hold")
    def test_stale_snapshot_holds(self):
        self.assertEqual(classify_restart("released", False, True, True, False).action, "hold")
    def test_open_orders_hold(self):
        self.assertEqual(classify_restart("released", False, True, False, True).action, "hold")
    def test_existing_owner_is_managed(self):
        self.assertEqual(classify_restart("filled", True, False, True, True).action, "manage_existing")
    def test_conflicting_owner_holds(self):
        self.assertEqual(classify_restart("filled", True, True, True, True).action, "hold")
    def test_unknown_intent_holds(self):
        self.assertEqual(classify_restart(None, False, True, True, True).action, "hold")
    def test_final_rejection_inspection_only(self):
        self.assertEqual(classify_restart("rejected_final", False, True, True, True).action, "inspect_only")

if __name__ == "__main__":
    unittest.main()
