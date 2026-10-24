"""Offline guardrails for the staged SQL initializer. Does not connect to a database."""
from pathlib import Path
import re
import unittest

SQL = Path("db/initialize_bot_states_from_snapshots.sql").read_text()

class InitializerContractTests(unittest.TestCase):
    def test_only_function_definition_and_privileges(self):
        self.assertRegex(SQL.lower(), r"create or replace function public\.initialize_bot_states_from_snapshots")
        self.assertNotRegex(SQL.lower(), r"\b(call|select)\s+public\.initialize_bot_states_from_snapshots\s*\(")

    def test_rejects_existing_state(self):
        self.assertIn("Existing bot_state row detected", SQL)
        self.assertRegex(SQL.lower(), r"if exists\s*\(select 1 from public\.bot_state")

    def test_requires_three_verified_snapshots(self):
        self.assertIn("v_count <> 3", SQL)
        self.assertIn("s.verified = true", SQL)
        self.assertIn("s.verified_at is not null", SQL)
        self.assertIn("Three distinct snapshot IDs are required", SQL)

    def test_insert_not_upsert_or_delete(self):
        self.assertIn("insert into public.bot_state(bot, state, revision)", SQL.lower())
        self.assertNotIn("on conflict", SQL.lower())
        self.assertNotRegex(SQL.lower(), r"\bdelete\s+from\s+public\.bot_state\b")
        self.assertNotRegex(SQL.lower(), r"\bupdate\s+public\.bot_state\b")

    def test_privileges_and_lock(self):
        self.assertIn("pg_advisory_xact_lock", SQL)
        self.assertIn("revoke all on function", SQL.lower())
        self.assertIn("to service_role", SQL.lower())

if __name__ == "__main__":
    unittest.main()
