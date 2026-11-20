"""Offline signer-free Info service process/Unix-socket CI tests.

No HTTP, signer, secrets, trading SDK, database, order calls or external
accounts. Passing only confirms a same-UID synthetic fixture boundary.
"""
import multiprocessing
import os
import socket
import struct
import tempfile
import unittest

from offline_signer_free_info_fixture_ci import OfflineSignerFreeInfoScope
from offline_signer_free_info_service_ci import (
    request_offline_info_fixture, serve_one_offline_info_fixture,
)

ACCOUNT = "0x" + "1" * 40
SCOPE = OfflineSignerFreeInfoScope("mainnet", ACCOUNT)


def synthetic_snapshot(account=ACCOUNT):
    return {
        "environment":"mainnet",
        "account":account,
        "user_state":{
            "marginSummary":{"accountValue":"200"},
            "assetPositions":[{"position":{
                "coin":"SOL","szi":"0.25","entryPx":"100",
                "unrealizedPnl":"2","leverage":{"type":"cross","value":2},
            }}],
        },
        "spot_state":{"balances":[{"coin":"USDC","total":"10"}]},
        "all_mids":{"SOL":"105"},
        "meta":{"universe":[{"name":"SOL","szDecimals":3}]},
    }


def launch_service(path, ready, scope, snapshot):
    serve_one_offline_info_fixture(
        socket_path=path, allowed_peer_uid=os.getuid(),
        scope=scope, snapshot=snapshot,
        captured_at_ms=1000, ready=ready,
    )


@unittest.skipUnless(
    os.name == "posix" and hasattr(socket,"SO_PEERCRED"),
    "Linux peer credentials required for offline Unix Info fixture",
)
class SignerFreeInfoServiceTests(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory(prefix="readonly-info-ci-")
        self.addCleanup(self.dir.cleanup)
        os.chmod(self.dir.name,0o700)
        self.path=os.path.join(self.dir.name,"info.sock")
        self.ctx=multiprocessing.get_context("fork")
        self._saved=os.environ.get("OFFLINE_SNAPSHOT_CI")
        os.environ["OFFLINE_SNAPSHOT_CI"]="1"
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        if self._saved is None:
            os.environ.pop("OFFLINE_SNAPSHOT_CI",None)
        else:
            os.environ["OFFLINE_SNAPSHOT_CI"]=self._saved

    def start(self, scope=SCOPE, snapshot=None):
        ready=self.ctx.Event()
        proc=self.ctx.Process(target=launch_service,args=(
            self.path,ready,scope,synthetic_snapshot() if snapshot is None else snapshot,
        ))
        proc.start()
        self.addCleanup(self._cleanup,proc)
        self.assertTrue(ready.wait(timeout=5),"offline fixture server not ready")
        return proc

    @staticmethod
    def _cleanup(proc):
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=4)

    def done(self, proc):
        proc.join(timeout=5)
        self.assertFalse(proc.is_alive(),"offline fixture server hung")
        self.assertEqual(proc.exitcode,0)
        self.assertFalse(os.path.lexists(self.path))

    def test_separate_process_supplies_only_unauthenticated_info(self):
        proc=self.start()
        result=request_offline_info_fixture(
            socket_path=self.path,expected_server_uid=os.getuid(),
            scope=SCOPE,now_ms=1200,
        )
        self.done(proc)
        self.assertEqual(result.state,"fixture_only")
        self.assertFalse(result.origin_authenticated)
        self.assertFalse(result.history_complete)
        self.assertFalse(result.ownership_verified)
        self.assertFalse(result.submit_authorized)
        self.assertEqual(result.view.user_state(ACCOUNT)
                         ["marginSummary"]["accountValue"],"200")
        self.assertEqual(result.view.all_mids()["SOL"],"105")
        self.assertFalse(hasattr(result.view,"market_open"))
        self.assertFalse(hasattr(result.view,"market_close"))
        self.assertFalse(hasattr(result.view,"update_leverage"))
        with self.assertRaises(PermissionError):
            result.view.user_fills(ACCOUNT)
        with self.assertRaises(PermissionError):
            result.view.user_funding_history(ACCOUNT,100,200)

    def test_wrong_account_and_wrong_service_uid_hold(self):
        proc=self.start()
        # Pre-connection scope/UID failures must not consume one-shot server.
        bad=request_offline_info_fixture(
            socket_path=self.path,expected_server_uid=os.getuid()+1000,
            scope=SCOPE,now_ms=1200,
        )
        foreign=request_offline_info_fixture(
            socket_path=self.path,expected_server_uid=os.getuid(),
            scope=OfflineSignerFreeInfoScope("mainnet","0x"+"2"*40),
            now_ms=1200,
        )
        self.done(proc)
        self.assertEqual(bad.state,"hold")
        self.assertEqual(foreign.state,"hold")
        self.assertIsNone(bad.view)
        self.assertIsNone(foreign.view)
        self.assertFalse(foreign.ownership_verified)

    def test_stale_snapshot_and_absent_service_hold(self):
        missing=request_offline_info_fixture(
            socket_path=self.path,expected_server_uid=os.getuid(),
            scope=SCOPE,now_ms=1200,
        )
        self.assertEqual(missing.state,"hold")
        proc=self.start()
        stale=request_offline_info_fixture(
            socket_path=self.path,expected_server_uid=os.getuid(),
            scope=SCOPE,now_ms=50000,
        )
        self.done(proc)
        self.assertEqual(stale.state,"hold")
        self.assertIsNone(stale.view)
        self.assertFalse(stale.submit_authorized)

    def test_unsupported_request_cannot_fetch_data(self):
        proc=self.start()
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
            conn.settimeout(3)
            conn.connect(self.path)
            request=b'{"operation":"send_order"}'
            conn.sendall(struct.pack("!I",len(request))+request)
            header=conn.recv(4)
            self.assertEqual(len(header),4)
            size=struct.unpack("!I",header)[0]
            self.assertLessEqual(size,1024)
            response=bytearray()
            while len(response)<size:
                data=conn.recv(size-len(response))
                self.assertTrue(data)
                response.extend(data)
        self.done(proc)
        self.assertEqual(bytes(response),
                         b'{"state":"hold","submit_authorized":false}')

    def test_private_socket_permissions_and_missing_flag_hold(self):
        proc=self.start()
        self.assertEqual(os.stat(self.dir.name).st_mode & 0o777,0o700)
        self.assertEqual(os.stat(self.path).st_mode & 0o777,0o600)
        os.environ.pop("OFFLINE_SNAPSHOT_CI")
        denied=request_offline_info_fixture(
            socket_path=self.path,expected_server_uid=os.getuid(),
            scope=SCOPE,now_ms=1200,
        )
        self.assertEqual(denied.state,"hold")
        os.environ["OFFLINE_SNAPSHOT_CI"]="1"
        result=request_offline_info_fixture(
            socket_path=self.path,expected_server_uid=os.getuid(),
            scope=SCOPE,now_ms=1200,
        )
        self.done(proc)
        self.assertEqual(result.state,"fixture_only")


if __name__=="__main__":
    unittest.main()
