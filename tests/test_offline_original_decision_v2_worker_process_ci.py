"""CI only: three distinct Linux UIDs run source-extracted original decisions.

Each unprivileged process has no signing key or PostgreSQL password. Only the
coordinator holds disposable DB credentials; a V2 review is not an order.
This test is not a substitute for production runtime isolation or protection
of existing positions and cannot authorize trading.
"""
import json
import multiprocessing
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile
import unittest

import psycopg

from test_offline_v2_distinct_uid_socket_postgres_ci import (
    ACCOUNT, BOTS, _disposable_ids, _serve,
)

ROOT = Path(__file__).resolve().parents[1]

# Only these reviewed CI modules and source-text-only executor files are
# staged. No package credentials, Git directory, deployment config, state,
# or server-side database password becomes accessible to bot identities.
STAGED_SOURCE_FILES = (
    "offline_original_decision_v2_worker_ci.py",
    "offline_original_read_helper_cutover_ci.py",
    "offline_original_sizing_v2_ci.py",
    "offline_original_signal_projection_ci.py",
    "offline_signer_free_read_bootstrap_ci.py",
    "offline_signer_free_bot_view_ci.py",
    "offline_signer_free_info_fixture_ci.py",
    "offline_leverage_bound_entry_draft_ci.py",
    "offline_original_executor_mutation_sink_ci.py",
    "offline_three_bot_mutation_review_ci.py",
    "offline_original_bot_intent_adapter.py",
    "offline_v2_signer_free_socket_client_ci.py",
    "hyperliquid_executor.py",
    "intraday_executor.py",
    "aggressive_executor.py",
)


def _stage_read_only_offline_worker(folder, group):
    """Root-owned/group-readable CI-only source, never the entire checkout."""
    stage = Path(folder) / "reviewed-worker"
    stage.mkdir(mode=0o750)
    os.chown(stage, 0, group)
    os.chmod(stage, 0o750)
    for name in STAGED_SOURCE_FILES:
        source = ROOT / name
        if not source.is_file() or source.is_symlink():
            raise AssertionError("unreviewed or missing staged source")
        target = stage / name
        target.write_bytes(source.read_bytes())
        os.chown(target, 0, group)
        os.chmod(target, 0o640)
        if (stat.S_IMODE(os.lstat(target).st_mode) != 0o640
                or os.lstat(target).st_gid != group):
            raise AssertionError("reviewed CI source permissions incorrect")
    return stage


@unittest.skipUnless(
    sys.platform.startswith("linux")
    and hasattr(os, "geteuid") and os.geteuid() == 0
    and hasattr(socket, "SO_PEERCRED")
    and os.environ.get("ISOLATED_POSTGRES_CI") == "1"
    and os.environ.get("PGDATABASE") == "safety_test"
    and os.environ.get("CI_V2_REVIEW_AUDIT") == "1",
    "requires root-only disposable Linux and PostgreSQL V2 CI",
)
class OriginalDecisionV2DistinctUIDTests(unittest.TestCase):
    @staticmethod
    def _rows():
        with psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="postgres", password=os.environ["PGPASSWORD"],
            autocommit=True,
        ) as conn:
            return conn.execute(
                "select bot,coin,requested_size,requested_leverage,state "
                "from public.ci_sender_v2_reviews"
            ).fetchall()

    @staticmethod
    def _run_bot(uid, group, bot, socket_path, action, source_root):
        def drop_permissions():
            os.setgroups([group])
            os.setgid(uid)
            os.setuid(uid)

        proc = subprocess.run(
            [sys.executable, "-m", "offline_original_decision_v2_worker_ci",
             bot, socket_path, str(group), str(source_root), action],
            preexec_fn=drop_permissions,
            cwd=str(source_root),
            env={
                "PATH": "/usr/bin:/bin",
                "PYTHONPATH": str(source_root),
                "PYTHONDONTWRITEBYTECODE": "1",
                "ISOLATED_POSTGRES_CI": "1",
                "PGDATABASE": "safety_test",
                "PGHOST": "localhost",
                "CI_V2_REVIEW_AUDIT": "1",
            },
            capture_output=True, text=True, timeout=9, check=False,
        )
        if proc.returncode != 0:
            raise AssertionError(
                "isolated worker failed (status %d): %s" %
                (proc.returncode, proc.stderr[-500:]),
            )
        return json.loads(proc.stdout)

    def test_real_three_uid_original_decisions_submit_only_one_review(self):
        uids, group = _disposable_ids()
        with psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="postgres", password=os.environ["PGPASSWORD"],
            autocommit=True,
        ) as conn:
            conn.execute("truncate public.ci_sender_v2_reviews restart identity")
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory, 0o711)
            source_root = _stage_read_only_offline_worker(directory, group)
            self.assertEqual(
                stat.S_IMODE(os.lstat(source_root).st_mode), 0o750)
            ipc = os.path.join(directory, "ipc")
            os.mkdir(ipc)
            os.chown(ipc, 0, group)
            os.chmod(ipc, 0o710)
            sock = os.path.join(ipc, "review-v2.sock")
            ctx = multiprocessing.get_context("fork")
            ready = ctx.Event()
            server = ctx.Process(
                target=_serve, args=(sock, group, uids[:3], ready, 3),
            )
            server.start()
            try:
                self.assertTrue(ready.wait(timeout=8), "V2 listener not ready")
                self.assertEqual(stat.S_IMODE(os.lstat(sock).st_mode), 0o660)
                results = []
                for uid, bot in zip(uids, BOTS):
                    result = self._run_bot(
                        uid, group, bot, sock, "buy", source_root)
                    self.assertEqual(result["submit_authorized"], False)
                    self.assertEqual(result["leverage_applied"], False)
                    self.assertFalse(result["signer_imported"])
                    self.assertFalse(result["original_executor_imported"])
                    self.assertFalse(result["trading_secret_present"])
                    self.assertFalse(result["postgres_password_present"])
                    self.assertTrue(result["original_read_helpers_used"])
                    self.assertEqual(result["synthetic_equity"], 150.0)
                    self.assertEqual(result["synthetic_mid"], 125.0)
                    self.assertEqual(result["synthetic_size_decimals"], 3)
                    self.assertEqual(result["synthetic_position_count"], 0)
                    self.assertTrue(result["original_sizing_calculated"])
                    self.assertEqual(result["requested_leverage"], 2)
                    self.assertEqual(
                        result["synthetic_rounded_size"],
                        "0.24" if bot == "aggressive" else "0.16",
                    )
                    results.append(result)
                self.assertEqual(
                    [r["state"] for r in results],
                    ["recorded_review_only", "hold", "hold"],
                )
                server.join(timeout=8)
                self.assertEqual(server.exitcode, 0)
                rows = self._rows()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0][0:2], ("daily", "SOL"))
                self.assertEqual(str(rows[0][2]), "0.16")
                self.assertEqual(rows[0][3:], (2, "review_only"))
                self.assertFalse(os.path.lexists(sock))

                # An original protective-close decision must NEVER be
                # mislabelled as an entry or forwarded over this interface.
                close = self._run_bot(
                    uids[2], group, "aggressive", sock, "sell_exit",
                    source_root,
                )
                self.assertEqual(close["state"], "hold")
                self.assertFalse(close["review_recorded"])
                self.assertFalse(close["submit_authorized"])
                self.assertNotIn("original_read_helpers_used", close)
                self.assertNotIn("original_sizing_calculated", close)
                self.assertEqual(self._rows(), rows)
            finally:
                if server.is_alive():
                    server.terminate()
                    server.join(timeout=4)


if __name__ == "__main__":
    unittest.main()
