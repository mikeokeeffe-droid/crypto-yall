"""CI-only V2 client transport: genuine AF_UNIX peer, no signer/order.

Exercises a root-run disposable coordinator and explicit no-authority replies.
No exchange SDK, network endpoint, secret or bot process is used.
"""
import json
import os
import socket
import stat
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

from offline_leverage_bound_entry_draft_ci import (
    OfflineLeverageBoundEntrySink, OfflineLeverageDraft,
)
from offline_v2_signer_free_socket_client_ci import (
    request_v2_review_via_unix_socket_offline as request,
)

ACCOUNT = "0x" + "1" * 40


def draft():
    sink = OfflineLeverageBoundEntrySink(
        bot="daily",trade={"hl_coin":"SOL","action":"open_long"},
        environment="mainnet",account=ACCOUNT,
    )
    sink.update_leverage(2,"SOL",True)
    sink.market_open("SOL",True,1.6)
    assert sink.last_draft.state == "review_only"
    return sink.last_draft


@unittest.skipUnless(
    hasattr(socket,"SO_PEERCRED") and hasattr(os,"getuid"),
    "requires Linux peer credential socket",
)
class SignerFreeV2ClientTests(unittest.TestCase):
    def invoke(self, *, response=None, draft_override=None, drop=False):
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory,0o700)
            name=os.path.join(directory,"v2.sock")
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener:
                listener.bind(name)
                os.chmod(name,0o600)
                listener.listen(1)
                payloads=[]
                def reply():
                    with listener.accept()[0] as peer:
                        if drop:
                            return
                        header=peer.recv(4)
                        if len(header)!=4:
                            return
                        length=struct.unpack("!I",header)[0]
                        parts=[]
                        while length:
                            chunk=peer.recv(length)
                            if not chunk:return
                            parts.append(chunk)
                            length-=len(chunk)
                        payloads.append(json.loads(b"".join(parts)))
                        data=(response if type(response) is bytes
                              else json.dumps(response or {
                                  "state":"recorded_review_only",
                                  "submit_authorized":False,
                                  "leverage_applied":False,
                              }).encode("utf-8"))
                        peer.sendall(struct.pack("!I",len(data))+data)
                worker=threading.Thread(target=reply,daemon=True)
                worker.start()
                with patch.dict(os.environ,{
                    "ISOLATED_POSTGRES_CI":"1","PGDATABASE":"safety_test",
                    "PGHOST":"localhost","CI_V2_REVIEW_AUDIT":"1",
                }):
                    result=request(
                        socket_path=name,expected_coordinator_uid=os.getuid(),
                        draft=draft_override or draft(),
                    )
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
                return result,payloads

    def test_valid_ack_records_review_but_never_trading_rights(self):
        result,payloads=self.invoke()
        self.assertEqual(result.state,"recorded_review_only")
        self.assertTrue(result.review_recorded)
        self.assertFalse(result.submit_authorized)
        self.assertFalse(result.leverage_applied)
        self.assertEqual(len(payloads),1)
        self.assertEqual(payloads[0]["requested_leverage"],2)
        self.assertNotIn("bot",payloads[0])
        self.assertNotIn("account",payloads[0])
        self.assertNotIn("private_key",payloads[0])

    def test_server_hold_and_false_authority_fail_closed(self):
        variants=[
            {"state":"hold","submit_authorized":False,"leverage_applied":False},
            {"state":"recorded_review_only","submit_authorized":True,
             "leverage_applied":False},
            {"state":"recorded_review_only","submit_authorized":False,
             "leverage_applied":True},
            {"state":"authorised_order","submit_authorized":False,
             "leverage_applied":False},
            {"state":"recorded_review_only","submit_authorized":False,
             "leverage_applied":False,"cloid":"forged"},
            b'{"state":"hold","state":"recorded_review_only",'
            b'"submit_authorized":false,"leverage_applied":false}',
        ]
        for response in variants:
            with self.subTest(response=response):
                result,_=self.invoke(response=response)
                self.assertFalse(result.submit_authorized)
                self.assertFalse(result.leverage_applied)
                self.assertFalse(result.review_recorded)
                self.assertEqual(result.state,"hold")

    def test_missing_ack_and_payload_spoofing_hold(self):
        result,_=self.invoke(drop=True)
        self.assertEqual(result.state,"hold")
        self.assertFalse(result.submit_authorized)
        unsafe=OfflineLeverageDraft(
            state="review_only",
            review_json=json.dumps({
                **json.loads(draft().review_json),
                "account":ACCOUNT,
            }),
        )
        with patch.dict(os.environ,{
            "ISOLATED_POSTGRES_CI":"1","PGDATABASE":"safety_test",
            "PGHOST":"localhost","CI_V2_REVIEW_AUDIT":"1",
        }):
            result=request(socket_path="/tmp/absent-v2-review.sock",
                           expected_coordinator_uid=os.getuid(),draft=unsafe)
        self.assertEqual(result.state,"hold")
        self.assertFalse(result.review_recorded)

    def test_preflight_refuses_invalid_environment_or_group(self):
        with patch.dict(os.environ,{},clear=True):
            result=request(socket_path="/tmp/no-review.sock",
                           expected_coordinator_uid=os.getuid(),draft=draft())
        self.assertEqual(result.state,"hold")
        self.assertFalse(result.review_recorded)


if __name__=="__main__":
    unittest.main()
