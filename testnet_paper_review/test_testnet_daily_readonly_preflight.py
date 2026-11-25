"""Mocked read-only /info preflight; never contacts Hyperliquid."""
import json
import unittest
from unittest.mock import patch

from testnet_paper_review import testnet_daily_readonly_preflight as reader


class Response:
    def __init__(self, data, *, status=200, length=None):
        self.status = status
        self.data = data if type(data) is bytes else json.dumps(data).encode("utf8")
        self.length = length
    def getheader(self, header):
        return self.length if header == "Content-Length" else None
    def read(self, limit):
        return self.data[:limit]


class Conn:
    def __init__(self, response):
        self.response = response
        self.requests = []
        self.closed = False
    def request(self, *args, **kwargs):
        self.requests.append((args, kwargs))
    def getresponse(self):
        return self.response
    def close(self):
        self.closed = True


def state(positions=None):
    return {"assetPositions": [] if positions is None else positions,
            "marginSummary":{"accountValue":"1000"},
            "withdrawable":"1000"}


class TestnetReadOnlyPreflightTests(unittest.TestCase):
    def test_fixed_host_path_query_types(self):
        for name in ("clearinghouseState", "openOrders"):
            obj=json.loads(reader.query_body(name))
            self.assertEqual(obj["user"],reader.EXPECTED_ACCOUNT)
            self.assertEqual(obj["type"],name)
            self.assertEqual(obj["dex"],"")
        for name in ("exchange", "userFills", "order", "userRole", "/exchange"):
            with self.subTest(name=name),self.assertRaises(reader.ReadOnlyError):
                reader.query_body(name)

    def test_reads_only_two_fixed_testnet_requests(self):
        for kind, response in (
            ("clearinghouseState",state()),
            ("openOrders",[{"oid":1,"coin":"SOL"}])
        ):
            c=Conn(Response(response))
            self.assertEqual(reader.fetch_public_info(kind,connection_factory=lambda:c),response)
            self.assertTrue(c.closed)
            args,kwargs=c.requests[0]
            self.assertEqual(args[:2],("POST","/info"))
            self.assertEqual(json.loads(kwargs["body"])["type"],kind)
            self.assertNotIn("Authorization",kwargs["headers"])

    def test_existing_manual_sol_and_protective_orders_hold(self):
        fake_state=state([{"position":{"coin":"SOL","szi":"0.30"}}])
        orders=[{"coin":"SOL","reduceOnly":True,"orderType":"Take Profit Market"},
                {"coin":"SOL","reduceOnly":True,"orderType":"Stop Market"}]
        def fetch(k):
            return fake_state if k=="clearinghouseState" else orders
        result=reader.review_once(fetcher=fetch,clock=lambda:1000)
        self.assertEqual(result["positions"],1)
        self.assertEqual(result["open_orders"],2)
        self.assertEqual(result["decision"].status,"HOLD")
        self.assertFalse(result["decision"].allows_order)

    def test_empty_account_still_cannot_authorize_trading(self):
        calls=[]
        def fetch(k):
            calls.append(k)
            return state() if k=="clearinghouseState" else []
        result=reader.review_once(fetcher=fetch,clock=lambda:1000)
        self.assertEqual(calls,["clearinghouseState","openOrders"])
        self.assertEqual(result["decision"].status,"HOLD")
        self.assertFalse(result["decision"].allows_order)

    def test_missing_orders_or_timeout_fails_closed(self):
        def fail(k):
            if k=="clearinghouseState":
                return state()
            raise reader.ReadOnlyError("HOLD: timed out reading openOrders")
        with self.assertRaises(reader.ReadOnlyError):
            reader.review_once(fetcher=fail,clock=lambda:1000)
        values=iter((1000,1016))
        with self.assertRaises(reader.ReadOnlyError):
            reader.review_once(fetcher=lambda k:state() if k=="clearinghouseState" else [],
                               clock=lambda:next(values))

    def test_reject_http_malformed_oversize(self):
        for kind, reply in (
            ("clearinghouseState",Response(state(),status=503)),
            ("clearinghouseState",Response(b"not JSON")),
            ("clearinghouseState",Response([],status=200)),
            ("clearinghouseState",Response(state(),length=str(reader.MAX_BYTES+1))),
            ("openOrders",Response({"wrong":"type"})),
            ("openOrders",Response(b"x"*(reader.MAX_BYTES+1))),
        ):
            c=Conn(reply)
            with self.subTest(kind=kind,reply=reply),self.assertRaises(reader.ReadOnlyError):
                reader.fetch_public_info(kind,connection_factory=lambda:c)
            self.assertTrue(c.closed)

    def test_no_manual_flag_no_io(self):
        with patch.object(reader,"review_once") as call:
            self.assertEqual(reader.main([]),2)
            call.assert_not_called()

    def test_uses_only_read_only_transport(self):
        import ast
        from pathlib import Path
        tree=ast.parse(Path(reader.__file__).read_text())
        imports={n.module.split(".")[0] for n in ast.walk(tree)
                 if isinstance(n,ast.ImportFrom) and n.module}
        imports|={a.name.split(".")[0] for n in ast.walk(tree)
                  if isinstance(n,ast.Import) for a in n.names}
        self.assertFalse({"hyperliquid","requests","eth_account","subprocess"}.intersection(imports))
        methods={n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
        self.assertFalse({"execute_trade","submit_order","market_open","market_close"}.intersection(methods))


if __name__ == "__main__":
    unittest.main()
