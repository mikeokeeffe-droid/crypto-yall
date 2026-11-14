"""Non-signing V2 socket review against disposable PostgreSQL safety_test.

The socket peer UID determines bot/account/environment; the wire cannot.
No real exchange connection or order path. Same-UID local fixture does not
prove three-way service isolation; distinct-UID tests are separate.
"""
import json
import os
import socket
import struct
import threading
import unittest

import psycopg

from offline_original_v2_socket_review_ci import (
    handle_offline_v2_review_socket,
)

ACCOUNT = "0x" + "1" * 40


@unittest.skipUnless(
    os.environ.get("ISOLATED_POSTGRES_CI") == "1"
    and os.environ.get("PGDATABASE") == "safety_test",
    "disposable PostgreSQL only",
)
class V2SocketReviewTests(unittest.TestCase):
    @staticmethod
    def connection():
        return psycopg.connect(
            host="localhost",port=5432,dbname="safety_test",
            user="entry_login_daily",password="disposable-daily-only",
        )

    def setUp(self):
        with psycopg.connect(
            host="localhost",port=5432,dbname="safety_test",
            user="postgres",password=os.environ["PGPASSWORD"],
            autocommit=True,
        ) as db:
            db.execute("truncate public.ci_sender_v2_reviews restart identity")
        self.old=os.environ.get("CI_V2_REVIEW_AUDIT")
        os.environ["CI_V2_REVIEW_AUDIT"]="1"

    def tearDown(self):
        if self.old is None:
            os.environ.pop("CI_V2_REVIEW_AUDIT",None)
        else:
            os.environ["CI_V2_REVIEW_AUDIT"]=self.old

    @staticmethod
    def draft():
        return {
            "operation": "review_entry_leverage_v2",
            "action": "open_long",
            "side": "long",
            "hl_coin": "SOL",
            "rounded_size": "1.6",
            "requested_leverage": 2,
            "cross_margin_requested": True,
        }

    def run_request(self, payload, *, allow=True, raw=None):
        # Two connected AF_UNIX endpoints, with kernel SO_PEERCRED enabled.
        # Handler runs in one thread; peer writes a bounded framed message.
        server,client=socket.socketpair(socket.AF_UNIX,socket.SOCK_STREAM)
        allowlist={os.getuid():("daily","mainnet",ACCOUNT)} if allow else {}
        result=[]
        def work():
            try:
                result.append(handle_offline_v2_review_socket(
                    server,allowlist,{"daily":self.connection}))
            finally:
                server.close()
        thread=threading.Thread(target=work,daemon=True)
        thread.start()
        try:
            data = raw if raw is not None else json.dumps(payload).encode()
            client.sendall(struct.pack("!I",len(data))+data)
            client.shutdown(socket.SHUT_WR)
        except (OSError,BrokenPipeError):
            pass
        finally:
            client.close()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(result),1)
        return result[0]

    def rows(self):
        with psycopg.connect(
            host="localhost",port=5432,dbname="safety_test",
            user="postgres",password=os.environ["PGPASSWORD"],
            autocommit=True,
        ) as db:
            return db.execute(
                "select bot,environment,effective_account,action,"
                "requested_size,requested_leverage,state "
                "from public.ci_sender_v2_reviews"
            ).fetchall()

    def test_kernel_pinned_identity_records_only_one_non_authorizing_review(self):
        first=self.run_request(self.draft())
        self.assertEqual(first.state,"recorded_review_only")
        self.assertFalse(first.submit_authorized)
        self.assertFalse(first.leverage_applied)
        again=self.run_request(self.draft())
        self.assertEqual(again.state,"hold")
        self.assertEqual(len(self.rows()),1)
        row=self.rows()[0]
        self.assertEqual(row[:4],("daily","mainnet",ACCOUNT,"open_long"))
        self.assertEqual(str(row[4]),"1.6")
        self.assertEqual(row[5:],(2,"review_only"))

    def test_spoofed_identity_and_malformed_requests_never_persist(self):
        cases=[
            dict(self.draft(), bot="aggressive"),
            dict(self.draft(), account=ACCOUNT),
            dict(self.draft(), environment="testnet"),
            dict(self.draft(), private_key="test"),
            dict(self.draft(), requested_leverage=True),
            dict(self.draft(), requested_leverage=0),
            dict(self.draft(), action="close"),
            dict(self.draft(), cross_margin_requested=False),
            dict(self.draft(), rounded_size="-1"),
            dict(self.draft(), submit_authorized=True),
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                r=self.run_request(payload)
                self.assertEqual(r.state,"hold")
                self.assertFalse(r.submit_authorized)
        self.assertEqual(self.run_request(self.draft(),allow=False).state,"hold")
        self.assertEqual(self.run_request({},raw=b'{"operation":1,"operation":2}').state,"hold")
        self.assertEqual(self.rows(),[])


if __name__=="__main__":
    unittest.main()
