"""Opt-in, read-only permission checks for an already provisioned PG18 socket DB.

This suite does not provision roles or mutate journal data. It requires an
explicit operator opt-in and connects only through the configured Unix socket.
"""

import os
from pathlib import Path
import unittest

try:
    import psycopg
except ModuleNotFoundError as exc:
    psycopg = None
    _psycopg_import_error = exc
else:
    _psycopg_import_error = None

from sender_review.postgresql18_offline.socket_policy import (
    verify_socket_directory,
)

ROLES = (
    "sender_review_pg18_daily",
    "sender_review_pg18_intraday",
    "sender_review_pg18_aggressive",
    "sender_review_ci_untrusted",
)
BOT_ROLES = ROLES[:3]
_socket_dir = os.environ.get("PGHOST", "")
_opted_in = os.environ.get("SENDER_REVIEW_PG18_OFFLINE") == "1"
_valid_configuration = (
    os.environ.get("PGDATABASE") == "sender_review_test"
    and Path(_socket_dir).is_absolute()
    and bool(os.environ.get("SENDER_REVIEW_PG18_SOCKET_GROUP"))
    and not os.environ.get("PGPORT")
)
if _opted_in and psycopg is None:
    raise RuntimeError(
        "psycopg is required when PostgreSQL 18 permission checks are enabled"
    ) from _psycopg_import_error
if _opted_in and not _valid_configuration:
    raise RuntimeError(
        "explicit PostgreSQL 18 opt-in requires the dedicated database, "
        "absolute Unix socket path, socket group, and no PGPORT"
    )
_enabled = _opted_in


def connect():
    return psycopg.connect(
        host=_socket_dir,
        dbname="sender_review_test",
        user=os.environ.get("PGUSER", "postgres"),
        password="",
        sslmode="disable",
        autocommit=False,
    )


@unittest.skipUnless(
    _enabled,
    "PostgreSQL 18 host permission checks were not explicitly enabled",
)
class PostgreSQL18PermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        group = os.environ["SENDER_REVIEW_PG18_SOCKET_GROUP"]
        verify_socket_directory(_socket_dir, group)
        with connect() as conn:
            if not conn.execute(
                "SELECT rolsuper FROM pg_catalog.pg_roles "
                "WHERE rolname = current_user"
            ).fetchone()[0]:
                raise RuntimeError("local postgres administrator required")

    def test_server_uses_only_the_restricted_postgresql18_socket(self):
        with connect() as conn:
            version, listen, socket_mode, socket_group, socket_dirs = conn.execute(
                "SELECT current_setting('server_version_num')::integer,"
                "current_setting('listen_addresses'),"
                "current_setting('unix_socket_permissions'),"
                "current_setting('unix_socket_group'),"
                "current_setting('unix_socket_directories')"
            ).fetchone()
        self.assertGreaterEqual(version, 180000)
        self.assertLess(version, 190000)
        self.assertEqual(listen, "")
        self.assertEqual(socket_mode, "0770")
        self.assertEqual(
            socket_group, os.environ["SENDER_REVIEW_PG18_SOCKET_GROUP"]
        )
        self.assertIn(_socket_dir, [item.strip() for item in socket_dirs.split(",")])

    def test_bot_roles_are_unloginable_ungranted_and_isolated(self):
        with connect() as conn:
            for role in ROLES:
                row = conn.execute(
                    "SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,"
                    "rolreplication,rolbypassrls,rolinherit,"
                    "has_database_privilege(%s,current_database(),'CONNECT'),"
                    "has_schema_privilege(%s,'sender_review_ci','USAGE'),"
                    "has_schema_privilege(%s,'sender_review_ci','CREATE') "
                    "FROM pg_catalog.pg_roles WHERE rolname=%s",
                    (role, role, role, role),
                ).fetchone()
                self.assertIsNotNone(row, role)
                self.assertEqual(row, (False, False, False, False, False,
                                       False, False, False, False, False))
                for privilege in ("CONNECT", "CREATE", "TEMPORARY"):
                    self.assertFalse(conn.execute(
                        "SELECT has_database_privilege("
                        "%s,current_database(),%s)",
                        (role, privilege),
                    ).fetchone()[0])
                for table in (
                    "fixture_identity_receipts",
                    "fixture_request_evidence",
                    "review_intents",
                    "review_events",
                    "scope_fences",
                ):
                    for privilege in (
                        "SELECT", "INSERT", "UPDATE", "DELETE",
                        "TRUNCATE", "REFERENCES", "TRIGGER",
                    ):
                        self.assertFalse(conn.execute(
                            "SELECT has_table_privilege(%s,%s,%s)",
                            (role, f"sender_review_ci.{table}", privilege),
                        ).fetchone()[0])
                for sequence in conn.execute(
                    "SELECT schemaname || '.' || sequencename "
                    "FROM pg_catalog.pg_sequences "
                    "WHERE schemaname='sender_review_ci'"
                ).fetchall():
                    for privilege in ("USAGE", "SELECT", "UPDATE"):
                        self.assertFalse(conn.execute(
                            "SELECT has_sequence_privilege(%s,%s,%s)",
                            (role, sequence[0], privilege),
                        ).fetchone()[0])
                for function in (
                    "sender_review_ci.record_review_only("
                    "text,text,text,text,text,numeric,integer,text)",
                    "sender_review_ci.hold_uncertain(text,text,text,bigint)",
                    "sender_review_ci.record_fixture_restricted("
                    "text,text,text,text,text,numeric,integer,text)",
                    "sender_review_ci.reject_fixture_evidence_mutation()",
                ):
                    self.assertFalse(conn.execute(
                        "SELECT has_function_privilege(%s,%s,'EXECUTE')",
                        (role, function),
                    ).fetchone()[0])
                self.assertEqual(conn.execute(
                    "SELECT count(*) FROM pg_catalog.pg_auth_members "
                    "WHERE roleid=(SELECT oid FROM pg_catalog.pg_roles "
                    "WHERE rolname=%s) OR member=(SELECT oid "
                    "FROM pg_catalog.pg_roles WHERE rolname=%s)",
                    (role, role),
                ).fetchone()[0], 0)
            for bot in BOT_ROLES:
                for other in BOT_ROLES:
                    if bot == other:
                        continue
                    self.assertFalse(conn.execute(
                        "SELECT pg_catalog.pg_has_role(%s,%s,'MEMBER')",
                        (bot, other),
                    ).fetchone()[0])

    def test_bot_roles_cannot_read_or_call_journal_functions(self):
        statements = (
            "SELECT * FROM sender_review_ci.review_intents",
            "SELECT sender_review_ci.record_review_only("
            "'0x1111111111111111111111111111111111111111',"
            "'daily','SOL','open_long','long',0.16,2,"
            "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')",
            "INSERT INTO sender_review_ci.review_intents "
            "(environment,account,dex,coin,bot,action,side,request_nonce,"
            "cloid,rounded_size,requested_leverage,fence) VALUES "
            "('testnet','0x1111111111111111111111111111111111111111',"
            "'','SOL','daily','open_long','long',"
            "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',"
            "'0x11111111111111111111111111111111',0.1,1,1)",
        )
        for role in ROLES:
            for statement in statements:
                with self.subTest(role=role, statement=statement[:30]):
                    conn = connect()
                    try:
                        conn.execute(f'SET ROLE "{role}"')
                        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                            conn.execute(statement)
                    finally:
                        conn.rollback()
                        conn.close()

    def test_fixture_role_has_only_its_review_wrapper(self):
        with connect() as conn:
            self.assertTrue(conn.execute(
                "SELECT has_schema_privilege("
                "'sender_review_ci_restricted','sender_review_ci','USAGE')"
            ).fetchone()[0])
            self.assertTrue(conn.execute(
                "SELECT has_function_privilege("
                "'sender_review_ci_restricted',"
                "'sender_review_ci.record_fixture_restricted("
                "text,text,text,text,text,numeric,integer,text)','EXECUTE')"
            ).fetchone()[0])
            self.assertFalse(conn.execute(
                "SELECT has_function_privilege("
                "'sender_review_ci_restricted',"
                "'sender_review_ci.record_review_only("
                "text,text,text,text,text,numeric,integer,text)','EXECUTE')"
            ).fetchone()[0])
            for table in (
                "fixture_identity_receipts",
                "fixture_request_evidence",
                "review_intents",
                "review_events",
                "scope_fences",
            ):
                self.assertFalse(conn.execute(
                    "SELECT has_table_privilege(%s,%s,'SELECT')",
                    ("sender_review_ci_restricted",
                     f"sender_review_ci.{table}"),
                ).fetchone()[0])


if __name__ == "__main__":
    unittest.main()
