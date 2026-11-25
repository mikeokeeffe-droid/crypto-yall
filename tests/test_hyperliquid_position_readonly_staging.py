"""Offline Hyperliquid position evidence tests with injected fake Info."""
import unittest
from hyperliquid_position_readonly_staging import read_position_evidence

class FakeInfo:
    def __init__(self, data=None, fail=False):
        self.data, self.fail = data, fail
    def user_state(self, address):
        if self.fail:
            raise ConnectionError("simulated outage")
        return self.data

class PositionReadOnlyTests(unittest.TestCase):
    def test_long_and_short_are_both_exposure(self):
        for signed_size in ("2.5", "-2.5"):
            with self.subTest(signed_size=signed_size):
                result = read_position_evidence(FakeInfo({"assetPositions":[
                    {"position":{"coin":"BTC","szi":signed_size}}]}), "fake", coin="BTC")
                self.assertTrue(result.confirmed)
                self.assertEqual(result.size, 2.5)

    def test_absent_coin_is_flat_in_valid_response(self):
        result = read_position_evidence(FakeInfo({"assetPositions":[
            {"position":{"coin":"ETH","szi":"4"}}]}), "fake", coin="BTC")
        self.assertEqual(result.size, 0)

    def test_malformed_duplicate_and_outage_fail_closed(self):
        states = [None, {}, {"assetPositions":[{"position":{"coin":"BTC","szi":"nan"}}]},
                  {"assetPositions":[{"position":{"coin":"BTC","szi":"1"}},
                                      {"position":{"coin":"BTC","szi":"2"}}]}]
        for state in states:
            with self.subTest(state=state):
                self.assertIsNone(read_position_evidence(FakeInfo(state), "fake", coin="BTC"))
        self.assertIsNone(read_position_evidence(FakeInfo(fail=True), "fake", coin="BTC"))

if __name__ == "__main__":
    unittest.main()
