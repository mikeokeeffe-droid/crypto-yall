import unittest
from hyperliquid_testnet_probe_staging import probe, fetch_info


ADDRESS = "0x" + "1" * 40


class ReadOnlyTestnetProbeTests(unittest.TestCase):
    def test_probe_uses_only_read_endpoints(self):
        calls = []
        def fake(kind, address):
            calls.append(kind)
            if kind == "clearinghouseState":
                return {"assetPositions": [{"position": {"coin": "BTC", "szi": "1"}}]}
            if kind == "openOrders":
                return [{"coin": "BTC"}]
            return [{"coin": "BTC", "oid": 123, "sz": "1"}]
        result = probe(ADDRESS, "BTC", fetch=fake)
        self.assertEqual(calls, ["clearinghouseState", "openOrders", "userFills"])
        self.assertFalse(result["position_flat"])
        self.assertEqual(result["coin_open_order_count"], 1)
        self.assertNotIn(ADDRESS, str(result))

    def test_invalid_address_rejected_before_network(self):
        with self.assertRaises(ValueError):
            probe("bad", "BTC", fetch=lambda *_: self.fail("network used"))

    def test_unsupported_request_rejected(self):
        with self.assertRaises(ValueError):
            fetch_info("order", ADDRESS, opener=lambda *_: self.fail("network used"))

    def test_malformed_response_rejected(self):
        def fake(kind, address):
            if kind == "clearinghouseState":
                return {"assetPositions": []}
            return {}
        with self.assertRaises(ValueError):
            probe(ADDRESS, "BTC", fetch=fake)


if __name__ == "__main__":
    unittest.main()
