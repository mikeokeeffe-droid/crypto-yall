"""Root-only, disposable Linux V2 review socket -> PostgreSQL integration.

Three *different* kernel UIDs share a group-connectable AF_UNIX socket.
The coordinator maps SO_PEERCRED UID to a fixed bot/account/environment and
keeps the restricted PostgreSQL credentials entirely in the root test server.
One synthetic review is persisted; competing requests, spoofing, outsiders,
and post-restart duplicates HOLD. No signer, SDK, exchange API or order.
This intentionally does NOT establish production workload isolation.
"""
import grp
import json
import multiprocessing
import os
import pwd
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import unittest

import psycopg
from offline_original_v2_socket_review_ci import handle_offline_v2_review_socket

ACCOUNT = "0x" + "1" * 40
BOTS = ("daily", "intraday", "aggressive")
_CHILD = """
import json,socket,struct,sys
body=json.loads(sys.argv[2])
data=json.dumps(body,separators=(',',':')).encode('utf-8')
def read_exact(sock,n):
    parts=[]
    while n:
        part=sock.recv(n)
        if not part: raise EOFError('truncated review response')
        parts.append(part)
        n-=len(part)
    return b''.join(parts)
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
    sock.settimeout(3)
    sock.connect(sys.argv[1])
    sock.sendall(struct.pack('!I',len(data))+data)
    sock.shutdown(socket.SHUT_WR)
    count=struct.unpack('!I',read_exact(sock,4))[0]
    response=json.loads(read_exact(sock,count))
print(json.dumps(response),flush=True)
"""


def _disposable_ids():
    existing_uids = {p.pw_uid for p in pwd.getpwall()}
    existing_gids = {g.gr_gid for g in grp.getgrall()}
    existing_gids.update(p.pw_gid for p in pwd.getpwall())
    uids = [n for n in range(51000, 61000) if n not in existing_uids][:4]
    group = next((n for n in range(51000, 61000)
                  if n not in existing_gids and n not in uids), None)
    if len(uids) < 4 or group is None:
        raise AssertionError("disposable Linux identities unavailable")
    return uids, group


def _review_request(**extra):
    return {
        "operation": "review_entry_leverage_v2",
        "action": "open_long", "side": "long", "hl_coin": "SOL",
        "rounded_size": "1.6", "requested_leverage": 2,
        "cross_margin_requested": True,
        **extra,
    }


def _serve(socket_path, group, uids, ready, max_requests):
    # This is a one-shot CI-only root process, NOT a deployable sender.
    # DB passwords are disposable and never passed to child bot processes.
    def factory(bot):
        return lambda: psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="entry_login_" + bot,
            password="disposable-" + bot + "-only",
        )
    allowlist = {uid: (bot, "mainnet", ACCOUNT)
                 for uid, bot in zip(uids, BOTS)}
    factories = {bot: factory(bot) for bot in BOTS}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(socket_path)
        inode = os.lstat(socket_path)
        try:
            os.chown(socket_path, 0, group)
            os.chmod(socket_path, 0o660)
            actual = os.lstat(socket_path)
            if (not stat.S_ISSOCK(actual.st_mode)
                    or actual.st_uid != 0 or actual.st_gid != group
                    or stat.S_IMODE(actual.st_mode) != 0o660):
                raise PermissionError("review socket group policy failed")
            listener.listen(max_requests)
            listener.settimeout(15)
            ready.set()
            for _ in range(max_requests):
                with listener.accept()[0] as conn:
                    result = handle_offline_v2_review_socket(
                        conn, allowlist, factories,
                    )
                    response = json.dumps({
                        "state": result.state,
                        "submit_authorized": False,
                        "leverage_applied": False,
                    }, separators=(",", ":")).encode("utf-8")
                    try:
                        conn.sendall(struct.pack("!I", len(response)) + response)
                    except OSError:
                        pass
        finally:
            try:
                current = os.lstat(socket_path)
                if ((current.st_dev, current.st_ino)
                        == (inode.st_dev, inode.st_ino)
                        and stat.S_ISSOCK(current.st_mode)):
                    os.unlink(socket_path)
            except FileNotFoundError:
                pass


@unittest.skipUnless(
    sys.platform.startswith("linux")
    and hasattr(os, "geteuid") and os.geteuid() == 0
    and hasattr(socket, "SO_PEERCRED")
    and os.environ.get("ISOLATED_POSTGRES_CI") == "1"
    and os.environ.get("PGDATABASE") == "safety_test"
    and os.environ.get("CI_V2_REVIEW_AUDIT") == "1",
    "requires root-only disposable Linux and PostgreSQL V2 review CI",
)
class ThreeUIDV2ReviewTests(unittest.TestCase):
    @staticmethod
    def run_as(uid, groups, path, payload):
        def drop():
            os.setgroups(groups)
            os.setgid(uid)
            os.setuid(uid)
        return subprocess.run(
            [sys.executable, "-c", _CHILD, path, json.dumps(payload)],
            preexec_fn=drop,
            env={"PATH": "/usr/bin:/bin"},
            capture_output=True, text=True, timeout=8, check=False,
        )

    @staticmethod
    def journal():
        with psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="postgres", password=os.environ["PGPASSWORD"],
            autocommit=True,
        ) as db:
            return db.execute(
                "select bot,environment,effective_account,coin,"
                "requested_size,requested_leverage,state,token,fence_token "
                "from public.ci_sender_v2_reviews"
            ).fetchall()

    def test_three_uids_spoofing_and_restart_preserve_one_review_only(self):
        uids, group = _disposable_ids()
        with psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="postgres", password=os.environ["PGPASSWORD"],
            autocommit=True,
        ) as db:
            db.execute("truncate public.ci_sender_v2_reviews restart identity")

        with tempfile.TemporaryDirectory() as root:
            os.chmod(root, 0o711)
            folder = os.path.join(root, "ipc")
            os.mkdir(folder)
            os.chown(folder, 0, group)
            os.chmod(folder, 0o710)
            path = os.path.join(folder, "review-v2.sock")
            self.assertEqual(stat.S_IMODE(os.stat(folder).st_mode), 0o710)
            ctx = multiprocessing.get_context("fork")
            ready = ctx.Event()
            server = ctx.Process(
                target=_serve,
                args=(path, group, uids[:3], ready, 5),
            )
            server.start()
            try:
                self.assertTrue(ready.wait(timeout=8), "V2 listener not ready")
                assert stat.S_IMODE(os.stat(path).st_mode) == 0o660
                results = []
                for uid in uids[:3]:
                    child = self.run_as(uid, [group], path, _review_request())
                    self.assertEqual(child.returncode, 0, child.stderr)
                    reply = json.loads(child.stdout)
                    self.assertFalse(reply["submit_authorized"])
                    self.assertFalse(reply["leverage_applied"])
                    results.append(reply["state"])
                self.assertEqual(results.count("recorded_review_only"), 1)
                self.assertEqual(results.count("hold"), 2)

                # A group member with an unapproved kernel UID is not a bot.
                outsider = self.run_as(
                    uids[3], [group], path, _review_request(),
                )
                self.assertEqual(outsider.returncode, 0, outsider.stderr)
                self.assertEqual(json.loads(outsider.stdout)["state"], "hold")

                # An approved bot cannot override identity through JSON.
                spoof = self.run_as(
                    uids[1], [group], path,
                    _review_request(bot="daily", account=ACCOUNT),
                )
                self.assertEqual(spoof.returncode, 0, spoof.stderr)
                self.assertEqual(json.loads(spoof.stdout)["state"], "hold")

                server.join(timeout=10)
                self.assertEqual(server.exitcode, 0, "V2 server failed")
                before = self.journal()
                self.assertEqual(len(before), 1, before)
                self.assertEqual(before[0][0:4],
                                 ("daily", "mainnet", ACCOUNT, "SOL"))
                self.assertEqual(str(before[0][4]), "1.6")
                self.assertEqual(before[0][5:7], (2, "review_only"))
                self.assertFalse(os.path.lexists(path))

                # No supplemental group: filesystem rejects the connection.
                ready2 = ctx.Event()
                restarted = ctx.Process(
                    target=_serve,
                    args=(path, group, uids[:3], ready2, 1),
                )
                restarted.start()
                try:
                    self.assertTrue(ready2.wait(timeout=8),
                                    "restarted V2 listener not ready")
                    denied = self.run_as(
                        uids[3], [], path, _review_request(),
                    )
                    self.assertNotEqual(denied.returncode, 0)
                    self.assertIn("PermissionError", denied.stderr)
                    # The previously recorded claim must still reject after
                    # restart, and no second row can be added.
                    duplicate = self.run_as(
                        uids[0], [group], path, _review_request(),
                    )
                    self.assertEqual(duplicate.returncode, 0, duplicate.stderr)
                    self.assertEqual(json.loads(duplicate.stdout)["state"],
                                     "hold")
                    restarted.join(timeout=10)
                    self.assertEqual(restarted.exitcode, 0)
                    self.assertEqual(self.journal(), before)
                    self.assertFalse(os.path.lexists(path))
                finally:
                    if restarted.is_alive():
                        restarted.terminate()
                        restarted.join(timeout=4)
            finally:
                if server.is_alive():
                    server.terminate()
                    server.join(timeout=4)


if __name__ == "__main__":
    unittest.main()
