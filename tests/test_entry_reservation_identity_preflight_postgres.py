"""Disposable PostgreSQL tests for the staging identity preflight."""
import os
from pathlib import Path
import secrets
import unittest
import uuid

import psycopg
from psycopg import sql


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = (ROOT / "db/entry_reservation_identity_preflight_staging.sql").read_text()
TABLES = (
    ("bot_entry_reservations", True),
    ("bot_entry_intents", True),
    ("bot_entry_executor_identities", False),
    ("bot_position_owners", False),
)
TABLE_PRIVILEGES = (
    "SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER",
)


@unittest.skipUnless(os.getenv("ISOLATED_POSTGRES_CI") == "1",
                     "only run on disposable PostgreSQL")
class EntryReservationIdentityPreflightPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = psycopg.connect(
            host=os.getenv("PGHOST", "localhost"),
            port=int(os.getenv("PGPORT", "5432")),
            dbname=os.getenv("PGDATABASE", "safety_test"),
            user=os.getenv("PGUSER", "postgres"),
            password=os.environ["PGPASSWORD"],
            autocommit=True,
        )
        cls.executor_logins = {
            bot: "preflight_" + bot + "_" + uuid.uuid4().hex[:8]
            for bot in ("aggressive", "intraday", "daily")
        }
        for bot, login in cls.executor_logins.items():
            cls.admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(login), sql.Literal(secrets.token_urlsafe(24))
                )
            )
            cls.admin.execute(
                sql.SQL("GRANT bot_entry_executor_trial TO {}").format(
                    sql.Identifier(login)
                )
            )
            cls.admin.execute(
                "insert into public.bot_entry_executor_identities (bot, db_login) "
                "values (%s, %s)",
                (bot, login),
            )

    @classmethod
    def tearDownClass(cls):
        cls.admin.execute(
            "delete from public.bot_entry_executor_identities where db_login = any(%s)",
            (list(cls.executor_logins.values()),),
        )
        for login in cls.executor_logins.values():
            cls.admin.execute(
                sql.SQL("REVOKE bot_entry_executor_trial FROM {}")
                .format(sql.Identifier(login))
            )
            cls.admin.execute(
                sql.SQL("DROP ROLE {}").format(sql.Identifier(login))
            )
        cls.admin.close()

    def run_preflight(self):
        self.admin.execute(PREFLIGHT)

    def assert_preflight_rejects(self, message):
        with self.assertRaises(psycopg.errors.RaiseException) as error:
            self.run_preflight()
        self.assertIn(message, str(error.exception))

    def test_allowed_executor_privileges_pass(self):
        self.run_preflight()

    def test_update_grant_on_intents_is_rejected(self):
        self.admin.execute(
            "GRANT UPDATE ON public.bot_entry_intents TO bot_entry_executor_trial"
        )
        try:
            self.assert_preflight_rejects(
                "executor has unexpected effective table privilege"
            )
        finally:
            self.admin.execute(
                "REVOKE UPDATE ON public.bot_entry_intents FROM bot_entry_executor_trial"
            )

    def test_column_update_grant_on_intents_is_rejected(self):
        self.admin.execute(
            "GRANT UPDATE (status) ON public.bot_entry_intents "
            "TO bot_entry_executor_trial"
        )
        try:
            self.assert_preflight_rejects(
                "executor has unexpected effective table privilege"
            )
        finally:
            self.admin.execute(
                "REVOKE UPDATE (status) ON public.bot_entry_intents "
                "FROM bot_entry_executor_trial"
            )

    def test_all_forbidden_table_privileges_are_rejected(self):
        for table, select_allowed in TABLES:
            for privilege in TABLE_PRIVILEGES:
                if privilege == "SELECT" and select_allowed:
                    continue
                with self.subTest(table=table, privilege=privilege):
                    grant = sql.SQL(
                        "GRANT {} ON TABLE {} TO bot_entry_executor_trial"
                    ).format(sql.SQL(privilege), sql.Identifier("public", table))
                    revoke = sql.SQL(
                        "REVOKE {} ON TABLE {} FROM bot_entry_executor_trial"
                    ).format(sql.SQL(privilege), sql.Identifier("public", table))
                    self.admin.execute(grant)
                    try:
                        self.assert_preflight_rejects(
                            "executor has unexpected effective table privilege"
                        )
                    finally:
                        self.admin.execute(revoke)

    def test_inherited_role_grant_is_rejected(self):
        inherited_role = "preflight_inherited_" + uuid.uuid4().hex
        self.admin.execute(
            sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(inherited_role))
        )
        try:
            self.admin.execute(
                sql.SQL("GRANT UPDATE ON public.bot_entry_intents TO {}")
                .format(sql.Identifier(inherited_role))
            )
            self.admin.execute(
                sql.SQL("GRANT {} TO bot_entry_executor_trial")
                .format(sql.Identifier(inherited_role))
            )
            self.assert_preflight_rejects(
                "executor inherits an unapproved database role"
            )
        finally:
            self.admin.execute(
                sql.SQL("REVOKE {} FROM bot_entry_executor_trial")
                .format(sql.Identifier(inherited_role))
            )
            self.admin.execute(
                sql.SQL("REVOKE UPDATE ON public.bot_entry_intents FROM {}")
                .format(sql.Identifier(inherited_role))
            )
            self.admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(inherited_role)))

    def test_inherited_supabase_admin_role_is_rejected(self):
        self.admin.execute("CREATE ROLE supabase_admin NOLOGIN")
        try:
            self.admin.execute(
                "GRANT supabase_admin TO bot_entry_executor_trial"
            )
            self.assert_preflight_rejects(
                "restricted role inherits a privileged database role"
            )
        finally:
            self.admin.execute(
                "REVOKE supabase_admin FROM bot_entry_executor_trial"
            )
            self.admin.execute("DROP ROLE supabase_admin")

    def test_missing_supabase_admin_role_is_allowed(self):
        exists = self.admin.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = 'supabase_admin'"
        ).fetchone()
        self.assertIsNone(exists)
        self.run_preflight()

    def test_unmapped_executor_login_is_rejected(self):
        login = "preflight_executor_login_" + uuid.uuid4().hex
        self.admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(login))
        )
        try:
            self.admin.execute(
                sql.SQL("GRANT bot_entry_executor_trial TO {}")
                .format(sql.Identifier(login))
            )
            self.assert_preflight_rejects(
                "executor login " + login + " has no bot identity mapping"
            )
        finally:
            self.admin.execute(
                sql.SQL("REVOKE bot_entry_executor_trial FROM {}")
                .format(sql.Identifier(login))
            )
            self.admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(login)))

    def test_executor_login_with_extra_inherited_role_is_rejected(self):
        login = "preflight_executor_login_" + uuid.uuid4().hex
        inherited_role = "preflight_login_extra_" + uuid.uuid4().hex
        prior_login = self.executor_logins["aggressive"]
        self.admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(login))
        )
        self.admin.execute(
            sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(inherited_role))
        )
        try:
            self.admin.execute(
                sql.SQL("GRANT UPDATE ON public.bot_entry_intents TO {}")
                .format(sql.Identifier(inherited_role))
            )
            self.admin.execute(
                sql.SQL("GRANT bot_entry_executor_trial, {} TO {}")
                .format(sql.Identifier(inherited_role), sql.Identifier(login))
            )
            self.admin.execute(
                sql.SQL("REVOKE bot_entry_executor_trial FROM {}")
                .format(sql.Identifier(prior_login))
            )
            self.admin.execute(
                "update public.bot_entry_executor_identities set db_login = %s "
                "where bot = 'aggressive'",
                (login,),
            )
            self.assert_preflight_rejects(
                f"executor login {login} inherits an unapproved database role"
            )
        finally:
            self.admin.execute(
                "update public.bot_entry_executor_identities set db_login = %s "
                "where bot = 'aggressive'",
                (prior_login,),
            )
            self.admin.execute(
                sql.SQL("GRANT bot_entry_executor_trial TO {}")
                .format(sql.Identifier(prior_login))
            )
            self.admin.execute(
                sql.SQL("REVOKE bot_entry_executor_trial, {} FROM {}")
                .format(sql.Identifier(inherited_role), sql.Identifier(login))
            )
            self.admin.execute(
                sql.SQL("REVOKE UPDATE ON public.bot_entry_intents FROM {}")
                .format(sql.Identifier(inherited_role))
            )
            self.admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(login)))
            self.admin.execute(
                sql.SQL("DROP ROLE {}").format(sql.Identifier(inherited_role))
            )

    def test_mapped_login_must_be_a_restricted_login(self):
        self.admin.execute(
            "update public.bot_entry_executor_identities "
            "set db_login = 'bot_entry_executor_trial' where bot = 'aggressive'"
        )
        try:
            self.assert_preflight_rejects(
                "mapped executor identity must be a restricted LOGIN member"
            )
        finally:
            self.admin.execute(
                "update public.bot_entry_executor_identities set db_login = %s "
                "where bot = 'aggressive'",
                (self.executor_logins["aggressive"],),
            )

    def test_unauthorized_rpc_execute_grant_is_rejected(self):
        signatures = (
            "public.resolve_bot_entry_intent(text,text,uuid)",
            "public.record_bot_position_owner(text,text,uuid,text,boolean)",
            "public.mark_bot_position_closed(text,text,uuid,boolean,boolean)",
            "public.release_closed_bot_position(text,text,uuid,boolean,boolean)",
        )
        for signature in signatures:
            with self.subTest(signature=signature):
                self.admin.execute(
                    sql.SQL("GRANT EXECUTE ON FUNCTION {} TO bot_entry_executor_trial")
                    .format(sql.SQL(signature))
                )
                try:
                    self.assert_preflight_rejects(
                        "executor has unexpected effective RPC privilege"
                    )
                finally:
                    self.admin.execute(
                        sql.SQL("REVOKE EXECUTE ON FUNCTION {} FROM bot_entry_executor_trial")
                        .format(sql.SQL(signature))
                    )

    def test_unlisted_public_rpc_execute_grant_is_rejected(self):
        function_name = "preflight_unlisted_" + uuid.uuid4().hex
        function = sql.SQL("{}()").format(sql.Identifier("public", function_name))
        self.admin.execute(
            sql.SQL("CREATE FUNCTION {} RETURNS integer LANGUAGE sql AS 'SELECT 1'")
            .format(function)
        )
        try:
            self.admin.execute(
                sql.SQL("REVOKE ALL ON FUNCTION {} FROM PUBLIC").format(function)
            )
            self.admin.execute(
                sql.SQL("GRANT EXECUTE ON FUNCTION {} TO bot_entry_executor_trial")
                .format(function)
            )
            self.assert_preflight_rejects(
                "executor has EXECUTE on an unapproved public routine"
            )
        finally:
            self.admin.execute(
                sql.SQL("REVOKE EXECUTE ON FUNCTION {} FROM bot_entry_executor_trial")
                .format(function)
            )
            self.admin.execute(sql.SQL("DROP FUNCTION {}").format(function))


if __name__ == "__main__":
    unittest.main()