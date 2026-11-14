"""Root-only disposable PG + real one-shot listener + three independent UIDs.

Verifies the ACTUAL group-gated offline listener and signer-free client;
no trading signer, live APIs, production database, order or close endpoint.
No production-credential isolation is proven by these temporary CI UIDs.
"""
import grp
import json
import multiprocessing
import os
import pwd
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import psycopg
from offline_original_bot_process_listener_ci import serve_offline_original_entry_requests

ACCOUNT = "0x" + "1" * 40
SOURCE_ROOT = Path(__file__).resolve().parents[1]
BOTS = ("daily", "intraday", "aggressive")
_CHILD = """
import json,os,sys
from offline_original_bot_entry_socket_client_ci import request_offline_entry_via_unix_socket
result=request_offline_entry_via_unix_socket(
 socket_path=sys.argv[1],expected_coordinator_uid=int(sys.argv[2]),
 verified_bot=sys.argv[3],
 trade={'action':'open_long','side':'long','hl_coin':sys.argv[4]},
 rounded_size='0.025',pinned_environment='mainnet',
 pinned_account='0x'+'1'*40,ipc_group_gid=int(sys.argv[5]))
print(json.dumps({'state':result.state,'submit_authorized':result.submit_authorized}),flush=True)
"""
_RAW_CONNECT = """
import socket,sys
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
    sock.settimeout(2)
    sock.connect(sys.argv[1])
"""


def _ids():
    used_uids = {p.pw_uid for p in pwd.getpwall()}
    used_gids = {g.gr_gid for g in grp.getgrall()}
    used_gids.update(p.pw_gid for p in pwd.getpwall())
    uids = [v for v in range(51000, 61000) if v not in used_uids][:4]
    gid = next((v for v in range(51000, 61000)
                if v not in used_gids and v not in uids), None)
    if len(uids) < 4 or gid is None:
        raise AssertionError("disposable identities unavailable")
    return uids, gid


def _server(path, gids, uids, ready):
    def db(bot):
        return lambda: psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="entry_login_" + bot,
            password="disposable-" + bot + "-only")
    serve_offline_original_entry_requests(
        socket_path=path, ipc_group_gid=gids,
        allowed_uids={uid: (bot,"mainnet",ACCOUNT)
                      for uid,bot in zip(uids,BOTS)},
        connection_factories={bot:db(bot) for bot in BOTS},
        max_requests=4, ready=ready, timeout=15.0)


@unittest.skipUnless(
    sys.platform.startswith("linux") and hasattr(os, "geteuid")
    and os.geteuid() == 0 and hasattr(socket, "SO_PEERCRED")
    and os.environ.get("ISOLATED_POSTGRES_CI") == "1"
    and os.environ.get("PGDATABASE") == "safety_test"
    and os.environ.get("CI_SOCKET_GROUP_AUDIT") == "1",
    "requires explicit root-only disposable PostgreSQL/Linux CI",
)
class GroupGatedRealProcessListenerTests(unittest.TestCase):
    def test_three_real_uids_use_signer_free_client_and_one_pending_claim(self):
        uids,gid = _ids()
        with psycopg.connect(
            host="localhost",port=5432,dbname="safety_test",
            user="postgres",password=os.environ["PGPASSWORD"],
            autocommit=True) as db:
            db.execute("truncate public.ci_scoped_entry_intents, "
                       "public.ci_scoped_entry_claims")
        with tempfile.TemporaryDirectory() as root:
            os.chmod(root,0o711)
            # The GitHub Actions checkout can be inside a runner-private
            # home directory. Stage ONLY the two non-networking client
            # modules into a disposable, root-owned read-only import path
            # traversable by all three synthetic bot UIDs. Do not change
            # runner home permissions or expose PostgreSQL credentials.
            client_dir = os.path.join(root,"client_modules")
            os.mkdir(client_dir,0o755)
            for module in (
                "offline_original_bot_entry_socket_client_ci.py",
                "offline_original_bot_intent_adapter.py",
            ):
                dest=os.path.join(client_dir,module)
                shutil.copyfile(SOURCE_ROOT / module,dest)
                os.chmod(dest,0o644)
            directory = os.path.join(root,"ipc")
            os.mkdir(directory)
            os.chown(directory,0,gid)
            os.chmod(directory,0o710)
            path = os.path.join(directory,"coordinator.sock")
            ctx = multiprocessing.get_context("fork")
            ready = ctx.Event()
            process = ctx.Process(target=_server,args=(path,gid,uids[:3],ready))
            process.start()
            try:
                self.assertTrue(ready.wait(timeout=8),"listener not ready")
                outcomes=[]
                for uid,bot in zip(uids[:3],BOTS):
                    def drop(uid=uid):
                        os.setgroups([gid])
                        os.setgid(uid)
                        os.setuid(uid)
                    env={"PATH":"/usr/bin:/bin","PYTHONPATH":client_dir,
                         "ISOLATED_POSTGRES_CI":"1","PGDATABASE":"safety_test",
                         "PGHOST":"localhost","CI_SOCKET_GROUP_AUDIT":"1"}
                    child=subprocess.run(
                        [sys.executable,"-c",_CHILD,path,"0",bot,"SOL",str(gid)],
                        preexec_fn=drop,env=env,capture_output=True,text=True,
                        timeout=8,check=False)
                    self.assertEqual(child.returncode,0,child.stderr)
                    parsed=json.loads(child.stdout)
                    self.assertFalse(parsed["submit_authorized"])
                    outcomes.append(parsed["state"])
                # Group membership is not authorization: an unknown UID
                # with socket-group access must be rejected by SO_PEERCRED.
                # An unknown UID WITHOUT group access must fail at the
                # filesystem socket boundary before reaching the listener.
                outsider_uid = uids[3]
                def drop_ungrouped():
                    os.setgroups([])
                    os.setgid(outsider_uid)
                    os.setuid(outsider_uid)
                no_group = subprocess.run(
                    [sys.executable,"-c",_RAW_CONNECT,path],
                    preexec_fn=drop_ungrouped,
                    env={"PATH":"/usr/bin:/bin"},capture_output=True,
                    text=True,timeout=5,check=False)
                self.assertNotEqual(no_group.returncode,0)
                self.assertIn("PermissionError",no_group.stderr)

                def drop_outsider():
                    os.setgroups([gid])
                    os.setgid(outsider_uid)
                    os.setuid(outsider_uid)
                outsider = subprocess.run(
                    [sys.executable,"-c",_CHILD,path,"0","daily","AVAX",str(gid)],
                    preexec_fn=drop_outsider,
                    env={"PATH":"/usr/bin:/bin","PYTHONPATH":client_dir,
                         "ISOLATED_POSTGRES_CI":"1","PGDATABASE":"safety_test",
                         "PGHOST":"localhost","CI_SOCKET_GROUP_AUDIT":"1"},
                    capture_output=True,text=True,timeout=8,check=False)
                self.assertEqual(outsider.returncode,0,outsider.stderr)
                self.assertEqual(json.loads(outsider.stdout),
                                 {"state":"hold","submit_authorized":False})

                process.join(timeout=8)
                self.assertEqual(process.exitcode,0,"listener did not exit cleanly")
                self.assertEqual(outcomes.count("recorded_offline_only"),1,outcomes)
                self.assertEqual(outcomes.count("hold"),2,outcomes)
                with psycopg.connect(
                    host="localhost",port=5432,dbname="safety_test",
                    user="postgres",password=os.environ["PGPASSWORD"],
                    autocommit=True) as db:
                    rows=db.execute(
                        "select bot,coin,status from public.ci_scoped_entry_intents"
                    ).fetchall()
                self.assertEqual(len(rows),1)
                self.assertIn(rows[0][0],BOTS)
                self.assertEqual(rows[0][1:3],("SOL","pending"))
                self.assertFalse(os.path.lexists(path))
            finally:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)


if __name__=="__main__":
    unittest.main()
