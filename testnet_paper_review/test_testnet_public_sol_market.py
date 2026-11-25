"""Mock-only tests of public SOL Testnet metadata/quote reads."""
import json
import unittest
from unittest.mock import patch
from pathlib import Path
from testnet_paper_review import testnet_public_sol_market as market

class Response:
    def __init__(self, result, status=200):
        self.status=status
        self.bytes=result if type(result) is bytes else json.dumps(result).encode()
    def getheader(self,name):
        return None
    def read(self,n):
        return self.bytes[:n]

class Conn:
    def __init__(self, response):
        self.response=response
        self.calls=[]
        self.closed=False
    def request(self,*args,**kwargs):
        self.calls.append((args,kwargs))
    def getresponse(self):
        return self.response
    def close(self):
        self.closed=True

def meta(sz=3):
    return {"universe":[{"name":"SOL","szDecimals":sz,"maxLeverage":10},
                        {"name":"BTC","szDecimals":5,"maxLeverage":20}]}
def mids():
    return {"SOL":"66.400","BTC":"100000"}

class TestnetSolMarketTests(unittest.TestCase):
    def test_only_fixed_public_market_queries(self):
        for k in ("meta","allMids"):
            self.assertEqual(json.loads(market.query_body(k)),{"type":k,"dex":""})
        for k in ("exchange","order","userFills","spotMeta"):
            with self.subTest(k=k),self.assertRaises(market.MarketReadHold):
                market.query_body(k)
    def test_hardcoded_testnet_public_info_only(self):
        for k,payload in (("meta",meta()),("allMids",mids())):
            conn=Conn(Response(payload))
            self.assertEqual(market.fetch_public_market(k,connection_factory=lambda:conn),payload)
            args,kw=conn.calls[0]
            self.assertEqual(args[:2],("POST","/info"))
            self.assertNotIn("Authorization",kw["headers"])
            self.assertTrue(conn.closed)
        self.assertEqual(market.HOST,"api.hyperliquid-testnet.xyz")
    def test_sol_metadata_drives_precision_but_no_order_permission(self):
        result=market.inspect_sol_market(meta=meta(),mids=mids(),start_s=100,finish_s=104)
        self.assertEqual(result.mid_price,"66.400")
        self.assertEqual(result.size_decimals,3)
        self.assertEqual(result.max_price_decimals,3)
        self.assertFalse(result.allows_trading)
    def test_read_two_sources_only(self):
        seen=[]
        def fetch(k):
            seen.append(k)
            return meta() if k=="meta" else mids()
        result=market.read_sol_market_once(fetcher=fetch,clock=lambda:100)
        self.assertEqual(seen,["meta","allMids"])
        self.assertFalse(result.allows_trading)
    def test_bad_meta_quote_precision_and_time_hold(self):
        cases=[
            {"meta":{}},
            {"meta":{"universe":[]}},
            {"meta":{"universe":[meta()["universe"][0],meta()["universe"][0]]}},
            {"meta":meta(sz=6)},
            {"meta":meta(sz=True)},
            {"meta":{"universe":[{"name":"SOL","szDecimals":3,"maxLeverage":0}]}},
            {"mids":{}},
            {"mids":{"SOL":"nan"}},
            {"mids":{"SOL":"0"}},
            {"mids":{"SOL":"9999999"}},
            {"start_s":0,"finish_s":11},
            {"start_s":4,"finish_s":3},
            {"start_s":True},
        ]
        for changes in cases:
            kwargs=dict(meta=meta(),mids=mids(),start_s=100,finish_s=104)
            kwargs.update(changes)
            with self.subTest(changes=changes),self.assertRaises(market.MarketReadHold):
                market.inspect_sol_market(**kwargs)
    def test_bad_http_json_response_hold(self):
        for response in (Response({},503),Response(b"not-json"),Response([]),
                         Response(b"x"*(market.MAX_BYTES+1))):
            conn=Conn(response)
            with self.subTest(response=response),self.assertRaises(market.MarketReadHold):
                market.fetch_public_market("meta",connection_factory=lambda:conn)
            self.assertTrue(conn.closed)
    def test_no_exchange_signing_surface(self):
        import ast
        tree=ast.parse(Path(market.__file__).read_text())
        imports={node.module.split(".")[0] for node in ast.walk(tree)
                 if isinstance(node,ast.ImportFrom) and node.module}
        imports|={a.name.split(".")[0] for node in ast.walk(tree)
                  if isinstance(node,ast.Import) for a in node.names}
        self.assertFalse({"hyperliquid","eth_account","requests","subprocess"} & imports)
        names={node.name for node in ast.walk(tree) if isinstance(node,ast.FunctionDef)}
        self.assertFalse({"submit_order","market_open","market_close","execute_trade","sign"} & names)

if __name__=="__main__":
    unittest.main()
