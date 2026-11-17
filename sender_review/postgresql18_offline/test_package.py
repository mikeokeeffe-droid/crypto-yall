"""Offline tests for the inert PostgreSQL 18 provisioning package."""

import grp
import os
from pathlib import Path
import tempfile
import unittest

from sender_review.postgresql18_offline.socket_policy import (
    verify_socket_directory,
)

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "sender_review" / "postgresql18_offline"


class SocketPolicyTests(unittest.TestCase):
    def test_accepts_exact_group_and_mode(self):
        group_name = grp.getgrgid(os.getgid()).gr_name
        with tempfile.TemporaryDirectory() as parent:
            socket_dir = Path(parent) / "socket"
            socket_dir.mkdir(mode=0o770)
            socket_dir.chmod(0o770)
            self.assertTrue(verify_socket_directory(str(socket_dir), group_name))

    def test_rejects_world_access_and_symlink(self):
        group_name = grp.getgrgid(os.getgid()).gr_name
        with tempfile.TemporaryDirectory() as parent:
            socket_dir = Path(parent) / "socket"
            socket_dir.mkdir(mode=0o770)
            socket_dir.chmod(0o777)
            with self.assertRaisesRegex(ValueError, "exactly 0770"):
                verify_socket_directory(str(socket_dir), group_name)
            link = Path(parent) / "link"
            link.symlink_to(socket_dir, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "real directory"):
                verify_socket_directory(str(link), group_name)

    def test_rejects_unexpected_group_and_non_absolute_path(self):
        with tempfile.TemporaryDirectory() as socket_dir:
            with self.assertRaisesRegex(ValueError, "expected group"):
                verify_socket_directory(socket_dir, "__missing_group__")
            with self.assertRaisesRegex(ValueError, "absolute path"):
                verify_socket_directory("relative/socket", "root")


class ProvisioningPackageTests(unittest.TestCase):
    def test_sql_fences_runtime_and_reuses_reviewed_sql(self):
        sql = (PACKAGE / "provision.sql").read_text(encoding="utf-8")
        for marker in (
            "current_database() <> 'sender_review_test'",
            "server_version_num",
            "current_setting('listen_addresses') <> ''",
            "current_setting('unix_socket_permissions') <> '0770'",
            "session_user <> 'postgres'",
            "\\ir ../ci_only_journal.sql",
            "\\ir ../ci_only_restricted_role.sql",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, sql)
        for role in (
            "sender_review_pg18_daily",
            "sender_review_pg18_intraday",
            "sender_review_pg18_aggressive",
        ):
            with self.subTest(role=role):
                role_sql = sql.split(f"CREATE ROLE {role}", 1)[1].split(";", 1)[0]
                self.assertIn("NOLOGIN", role_sql)
                self.assertIn(f"REVOKE ALL ON SCHEMA sender_review_ci", sql)
        self.assertNotIn("CREATE ROLE sender_review_pg18_daily LOGIN", sql)
        self.assertNotIn("HL_PRIVATE_KEY", sql)
        self.assertNotIn("market_open(", sql)
        self.assertNotIn("market_close(", sql)

    def test_docs_include_disabled_scope_and_rollback(self):
        docs = (
            ROOT / "docs" /
            "postgresql18-offline-test-server-provisioning-20261117.md"
        ).read_text(encoding="utf-8")
        for marker in (
            "Do not execute",
            "TCP",
            "0770",
            "NOLOGIN",
            "rollback",
            "RESTRICT",
            "DRAFT",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, docs)


if __name__ == "__main__":
    unittest.main()
