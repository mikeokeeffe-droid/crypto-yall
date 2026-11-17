"""Disposable PostgreSQL 18 integration test for the exact review package."""

import subprocess
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROVISION_SQL = (
    "/workspace/sender_review/postgresql18_offline/provision.sql"
)


class PostgreSQL18ProvisioningIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container = f"sender-review-pg18-{uuid.uuid4().hex[:12]}"
        command = [
            "docker", "run", "--detach", "--rm", "--name", cls.container,
            "--network", "none",
            "--env", "POSTGRES_HOST_AUTH_METHOD=trust",
            "--env", "POSTGRES_DB=sender_review_test",
            "--mount", f"type=bind,src={ROOT},dst=/workspace,readonly",
            "--tmpfs", "/tmp/pgsocket:rw,mode=0770,uid=999,gid=999",
            "postgres:18",
            "-c", "listen_addresses=",
            "-c", "unix_socket_directories=/tmp/pgsocket",
            "-c", "unix_socket_permissions=0770",
            "-c", "unix_socket_group=postgres",
        ]
        result = subprocess.run(
            command, capture_output=True, text=True, check=False
        )
        if result.returncode:
            raise RuntimeError(
                f"could not start disposable PostgreSQL 18: {result.stderr}"
            )
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            ready = cls.docker(
                "exec", cls.container, "pg_isready", "-h", "/tmp/pgsocket",
                "-U", "postgres",
                "-d", "sender_review_test", check=False,
            )
            if ready.returncode == 0:
                return
            time.sleep(1)
        logs = cls.docker("logs", cls.container, check=False)
        cls.docker("rm", "--force", cls.container, check=False)
        raise RuntimeError(
            "disposable PostgreSQL 18 did not become ready: "
            f"{logs.stdout}{logs.stderr}"
        )

    @classmethod
    def tearDownClass(cls):
        cls.docker("rm", "--force", cls.container, check=False)

    @classmethod
    def docker(cls, *args, check=True):
        return subprocess.run(
            ["docker", *args],
            capture_output=True,
            text=True,
            check=check,
        )

    @classmethod
    def psql(cls, statement=None, *, file=None, check=True):
        command = [
            "exec", cls.container, "psql", "-X", "-v", "ON_ERROR_STOP=1",
            "-h", "/tmp/pgsocket", "-U", "postgres",
            "-d", "sender_review_test",
        ]
        if file is not None:
            command.extend(["-f", file])
        else:
            command.extend(["--no-align", "--tuples-only", "--quiet",
                            "-F", "|",
                            "-c", statement])
        return cls.docker(*command, check=check)

    @classmethod
    def rows(cls, statement):
        return [
            tuple(line.split("|"))
            for line in cls.psql(statement).stdout.splitlines()
            if line
        ]

    def test_exact_package_privileges_isolation_and_transaction_rollback(self):
        self.psql(
            "CREATE ROLE sender_review_pg18_intraday NOLOGIN NOSUPERUSER "
            "NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT"
        )
        failed = self.psql(file=PROVISION_SQL, check=False)
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(
            self.psql(
                "SELECT string_agg(rolname, ',' ORDER BY rolname) "
                "FROM pg_catalog.pg_roles WHERE rolname IN "
                "('sender_review_pg18_owner','sender_review_pg18_daily',"
                "'sender_review_pg18_intraday')"
            ).stdout.strip(),
            "sender_review_pg18_intraday",
        )
        self.assertEqual(
            self.psql(
                "SELECT count(*) FROM pg_catalog.pg_namespace "
                "WHERE nspname='sender_review_ci'"
            ).stdout.strip(),
            "0",
        )
        self.psql("DROP ROLE sender_review_pg18_intraday")
        self.psql(file=PROVISION_SQL)

        self.assertEqual(
            self.psql(
                "SELECT current_setting('server_version_num')::integer "
                "BETWEEN 180000 AND 189999 AND "
                "current_setting('listen_addresses')='' AND "
                "current_setting('unix_socket_permissions')='0770' AND "
                "current_setting('unix_socket_group')='postgres'"
            ).stdout.strip(),
            "t",
        )
        self.assertEqual(
            self.docker(
                "exec", self.container, "stat", "-c", "%a:%G",
                "/tmp/pgsocket",
            ).stdout.strip(),
            "770:postgres",
        )
        self.assertEqual(
            self.docker(
                "exec", self.container, "stat", "-c", "%a:%G",
                "/tmp/pgsocket/.s.PGSQL.5432",
            ).stdout.strip(),
            "770:postgres",
        )

        roles = (
            "sender_review_pg18_owner",
            "sender_review_pg18_daily",
            "sender_review_pg18_intraday",
            "sender_review_pg18_aggressive",
            "sender_review_ci_untrusted",
            "sender_review_ci_restricted",
        )
        role_csv = ",".join(f"'{role}'" for role in roles)
        self.assertEqual(
            self.psql(
                "SELECT count(*) FROM pg_catalog.pg_roles "
                f"WHERE rolname IN ({role_csv}) AND "
                "NOT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb "
                "AND NOT rolcreaterole AND NOT rolreplication "
                "AND NOT rolbypassrls AND NOT rolinherit"
            ).stdout.strip(),
            str(len(roles)),
        )
        self.assertEqual(
            self.psql(
                "SELECT count(*) FROM pg_catalog.pg_auth_members m "
                "JOIN pg_catalog.pg_roles r ON "
                "(m.roleid=r.oid OR m.member=r.oid) "
                f"WHERE r.rolname IN ({role_csv})"
            ).stdout.strip(),
            "0",
        )
        self.assertEqual(
            self.psql(
                "SELECT count(*) FROM pg_catalog.pg_roles r "
                "WHERE r.rolname IN (" + role_csv + ") AND "
                "NOT has_database_privilege(r.rolname,current_database(),"
                "'CONNECT') AND "
                "NOT has_database_privilege(r.rolname,current_database(),"
                "'CREATE') AND "
                "NOT has_database_privilege(r.rolname,current_database(),"
                "'TEMPORARY')"
            ).stdout.strip(),
            str(len(roles)),
        )
        self.assertEqual(
            self.psql(
                "SELECT n.nspowner = (SELECT oid FROM pg_catalog.pg_roles "
                "WHERE rolname='sender_review_pg18_owner') "
                "FROM pg_catalog.pg_namespace n "
                "WHERE n.nspname='sender_review_ci'"
            ).stdout.strip(),
            "t",
        )
        schema_rows = self.rows(
            "SELECT rolname, "
            "has_schema_privilege(rolname,'sender_review_ci','USAGE'), "
            "has_schema_privilege(rolname,'sender_review_ci','CREATE') "
            f"FROM pg_catalog.pg_roles WHERE rolname IN ({role_csv}) "
            "ORDER BY rolname"
        )
        for role, usage, create in schema_rows:
            self.assertEqual(
                (usage, create),
                (
                    "t" if role in (
                        "sender_review_pg18_owner",
                        "sender_review_ci_restricted",
                    ) else "f",
                    "t" if role == "sender_review_pg18_owner" else "f",
                ),
                role,
            )
        self.assertEqual(
            self.psql(
                "SELECT count(*) FROM pg_catalog.pg_class c "
                "WHERE c.relnamespace='sender_review_ci'::regnamespace "
                "AND c.relkind IN ('r','p','S') "
                "AND c.relowner <> (SELECT oid FROM pg_catalog.pg_roles "
                "WHERE rolname='sender_review_pg18_owner')"
            ).stdout.strip(),
            "0",
        )
        self.assertEqual(
            self.psql(
                "SELECT count(*) FROM pg_catalog.pg_proc p "
                "JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname='sender_review_ci' "
                "AND p.proowner <> (SELECT oid FROM pg_catalog.pg_roles "
                "WHERE rolname='sender_review_pg18_owner')"
            ).stdout.strip(),
            "0",
        )

        table_rows = self.rows(
            "SELECT r.rolname, t.table_name, p.privilege, "
            "has_table_privilege(r.rolname,"
            "'sender_review_ci.' || t.table_name,p.privilege) "
            f"FROM pg_catalog.pg_roles r CROSS JOIN "
            "(VALUES ('fixture_identity_receipts'),"
            "('fixture_request_evidence'),('review_intents'),"
            "('review_events'),('scope_fences')) AS t(table_name) "
            "CROSS JOIN (VALUES ('SELECT'),('INSERT'),('UPDATE'),"
            "('DELETE'),('TRUNCATE'),('REFERENCES'),('TRIGGER')) "
            "AS p(privilege) "
            f"WHERE r.rolname IN ({role_csv}) "
            "ORDER BY r.rolname,t.table_name,p.privilege"
        )
        for role, table, privilege, granted in table_rows:
            self.assertEqual(
                granted,
                "t" if role == "sender_review_pg18_owner" else "f",
                f"unexpected {privilege} grant for {role} on {table}",
            )
        sequence_rows = self.rows(
            "SELECT r.rolname, s.sequencename, p.privilege, "
            "has_sequence_privilege(r.rolname,"
            "'sender_review_ci.' || s.sequencename,p.privilege) "
            f"FROM pg_catalog.pg_roles r CROSS JOIN "
            "(SELECT sequencename FROM pg_catalog.pg_sequences "
            "WHERE schemaname='sender_review_ci') s "
            "CROSS JOIN (VALUES ('USAGE'),('SELECT'),('UPDATE')) "
            "AS p(privilege) "
            f"WHERE r.rolname IN ({role_csv}) "
            "ORDER BY r.rolname,s.sequencename,p.privilege"
        )
        for role, sequence, privilege, granted in sequence_rows:
            self.assertEqual(
                granted,
                "t" if role == "sender_review_pg18_owner" else "f",
                f"unexpected {privilege} grant for {role} on {sequence}",
            )
        function_rows = self.rows(
            "SELECT r.rolname, p.proname, "
            "has_function_privilege(r.rolname,p.oid,'EXECUTE') "
            "FROM pg_catalog.pg_roles r CROSS JOIN pg_catalog.pg_proc p "
            "JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
            f"WHERE r.rolname IN ({role_csv}) "
            "AND n.nspname='sender_review_ci' "
            "ORDER BY r.rolname,p.proname"
        )
        for role, function, granted in function_rows:
            expected_execute = (
                role == "sender_review_pg18_owner"
                or (
                    role == "sender_review_ci_restricted"
                    and function == "record_fixture_restricted"
                )
            )
            self.assertEqual(
                granted,
                "t" if expected_execute else "f",
                f"unexpected EXECUTE grant for {role} on {function}",
            )
        membership_rows = self.rows(
            "SELECT src.rolname,dst.rolname,"
            "pg_catalog.pg_has_role(src.rolname,dst.rolname,'MEMBER') "
            "FROM pg_catalog.pg_roles src CROSS JOIN "
            "pg_catalog.pg_roles dst "
            f"WHERE src.rolname IN ({role_csv}) "
            f"AND dst.rolname IN ({role_csv}) "
            "AND src.rolname <> dst.rolname "
            "ORDER BY src.rolname,dst.rolname"
        )
        self.assertTrue(membership_rows)
        self.assertTrue(all(result == "f" for _, _, result in membership_rows))

        for role in roles[1:]:
            for statement in (
                "SELECT * FROM sender_review_ci.review_intents",
                "INSERT INTO sender_review_ci.scope_fences "
                "(environment,account,coin) VALUES "
                "('testnet','0x1111111111111111111111111111111111111111',"
                "'SOL')",
                "SELECT * FROM sender_review_ci.record_review_only("
                "'0x1111111111111111111111111111111111111111','daily','SOL',"
                "'open_long','long',0.1,1,"
                "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')",
                "CREATE SCHEMA sender_review_must_be_denied",
            ):
                denied = self.psql(
                    f'BEGIN; SET ROLE "{role}"; {statement}; ROLLBACK',
                    check=False,
                )
                self.assertNotEqual(
                    denied.returncode, 0,
                    f"{role} unexpectedly executed {statement}",
                )
            denied_membership = self.psql(
                f'SET SESSION AUTHORIZATION "{role}"; SET ROLE '
                f'"sender_review_pg18_{"intraday" if role == "sender_review_pg18_daily" else "daily"}"',
                check=False,
            )
            self.assertNotEqual(denied_membership.returncode, 0)

        self.assertEqual(
            self.psql(
                "SELECT has_schema_privilege('sender_review_ci_restricted',"
                "'sender_review_ci','USAGE') AND "
                "NOT has_schema_privilege('sender_review_ci_restricted',"
                "'sender_review_ci','CREATE') AND "
                "has_function_privilege('sender_review_ci_restricted',"
                "'sender_review_ci.record_fixture_restricted("
                "text,text,text,text,text,numeric,integer,text)','EXECUTE') "
                "AND NOT has_function_privilege('sender_review_ci_restricted',"
                "'sender_review_ci.record_review_only("
                "text,text,text,text,text,numeric,integer,text)','EXECUTE')"
            ).stdout.strip(),
            "t",
        )
        self.assertEqual(
            self.psql(
                "SELECT (SELECT count(*) FROM "
                "sender_review_ci.fixture_identity_receipts) + "
                "(SELECT count(*) FROM "
                "sender_review_ci.fixture_request_evidence) + "
                "(SELECT count(*) FROM sender_review_ci.review_intents) + "
                "(SELECT count(*) FROM sender_review_ci.review_events) + "
                "(SELECT count(*) FROM sender_review_ci.scope_fences)"
            ).stdout.strip(),
            "0",
        )
