import io
import json
import unittest
from hyperliquid_public_testnet_smoke import check_public_testnet


class Response:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self): return io.BytesIO(json.dumps(self.payload).encode())
    def __exit__(self, *_): return False


class PublicTestnetSmokeTests(unittest.TestCase):
    def test_public_metadata_read_only(self):
        def fake(req, timeout):
            self.assertEqual(req.full_url, "https://api.hyperliquid-testnet.xyz/info")
            self.assertEqual(json.loads(req.data), {"type": "meta"})
            return Response({"universe": [{"name": "BTC"}]})
        self.assertEqual(check_public_testnet(opener=fake), 1)

    def test_bad_metadata_fails(self):
        with self.assertRaises(RuntimeError):
            check_public_testnet(opener=lambda *_args, **_kwargs: Response({}))


if __name__ == "__main__":
    unittest.main()
