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
    def _run_bot(uid, group, bot, socket_path, action):
        def drop_permissions():
            os.setgroups([group])
            os.setgid(uid)
            os.setuid(uid)

        proc = subprocess.run(
            [sys.executable, "-m", "offline_original_decision_v2_worker_ci",
             bot, socket_path, str(group), str(ROOT), action],
            preexec_fn=drop_permissions,
            env={
                "PATH": "/usr/bin:/bin",
                "PYTHONPATH": str(ROOT),
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
                    result = self._run_bot(uid, group, bot, sock, "buy")
                    self.assertEqual(result["submit_authorized"], False)
                    self.assertEqual(result["leverage_applied"], False)
                    self.assertFalse(result["signer_imported"])
                    self.assertFalse(result["original_executor_imported"])
                    self.assertFalse(result["trading_secret_present"])
                    self.assertFalse(result["postgres_password_present"])
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
                self.assertEqual(str(rows[0][2]), "1.6")
                self.assertEqual(rows[0][3:], (2, "review_only"))
                self.assertFalse(os.path.lexists(sock))

                # An original protective-close decision must NEVER be
                # mislabelled as an entry or forwarded over this interface.
                close = self._run_bot(
                    uids[2], group, "aggressive", sock, "sell_exit",
                )
                self.assertEqual(close["state"], "hold")
                self.assertFalse(close["review_recorded"])
                self.assertFalse(close["submit_authorized"])
                self.assertEqual(self._rows(), rows)
            finally:
                if server.is_alive():
                    server.terminate()
                    server.join(timeout=4)


if __name__ == "__main__":
    unittest.main()
