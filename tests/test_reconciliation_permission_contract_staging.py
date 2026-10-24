"""Static security contract for staging ownership handoff.

This test intentionally fails until the routine executor role loses
permission to assert that its own fill was independently verified.
"""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ReconciliationPermissionContract(unittest.TestCase):
    def test_routine_role_cannot_self_certify_fill(self):
        sql = (ROOT / "db/position_ownership_staging.sql").read_text()
        signature = "public.record_bot_position_owner(text,text,uuid,text,boolean)"
        unsafe_grant = (
            "grant execute on function " + signature + "\n to service_role;"
        )
        self.assertNotIn(unsafe_grant, sql,
                         "Routine service_role must not self-certify exchange fills")

    def test_reconciliation_roles_are_explicit(self):
        sql = (ROOT / "db/position_ownership_staging.sql").read_text()
        self.assertIn("record_bot_position_owner", sql)
        self.assertIn("mark_bot_position_closed", sql)
        self.assertIn("release_closed_bot_position", sql)


if __name__ == "__main__":
    unittest.main()
