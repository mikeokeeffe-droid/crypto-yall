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

    def test_service_role_cannot_execute_close_or_release_routines(self):
        sql = (ROOT / "db/position_ownership_staging.sql").read_text()
        for signature in (
            "public.mark_bot_position_closed(text,text,uuid,boolean,boolean)",
            "public.release_closed_bot_position(text,text,uuid,boolean,boolean)",
        ):
            with self.subTest(signature=signature):
                revoke = re.compile(
                    r"revoke\s+all\s+on\s+function\s+"
                    + re.escape(signature)
                    + r"\s+from\s+[^;]*\bservice_role\b",
                    re.IGNORECASE,
                )
                self.assertRegex(sql, revoke)

    def test_service_role_has_no_entry_table_access_in_staging_grants(self):
        grants = (ROOT / "db/entry_reservations_staging_grants.sql").read_text()
        ownership = (ROOT / "db/position_ownership_staging.sql").read_text()
        for table in (
            "bot_entry_reservations",
            "bot_entry_intents",
        ):
            self.assertRegex(
                grants,
                re.compile(
                    rf"revoke\s+all\s+on\s+public\.{table}\s+from\s+service_role",
                    re.IGNORECASE,
                ),
            )
            self.assertNotRegex(
                grants,
                re.compile(
                    rf"grant\s+select\s+on\s+public\.{table}\s+to\s+service_role",
                    re.IGNORECASE,
                ),
            )
        self.assertRegex(
            ownership,
            re.compile(
                r"revoke\s+all\s+on\s+public\.bot_position_owners\s+"
                r"from\s+service_role",
                re.IGNORECASE,
            ),
        )
        self.assertNotRegex(
            ownership,
            re.compile(
                r"grant\s+select\s+on\s+public\.bot_position_owners\s+"
                r"to\s+service_role",
                re.IGNORECASE,
            ),
        )

    def test_readonly_preflight_checks_close_and_release_privileges(self):
        preflight = (
            ROOT / "db/entry_reservation_identity_preflight_staging.sql"
        ).read_text()
        for signature in (
            "public.mark_bot_position_closed(text,text,uuid,boolean,boolean)",
            "public.release_closed_bot_position(text,text,uuid,boolean,boolean)",
        ):
            self.assertIn(signature, preflight)
        self.assertIn("pg_has_role(", preflight)
        self.assertIn("p.prosecdef", preflight)
        self.assertIn("search_path=pg_catalog, public", preflight)
        self.assertIn("has_schema_privilege(", preflight)


if __name__ == "__main__":
    unittest.main()
