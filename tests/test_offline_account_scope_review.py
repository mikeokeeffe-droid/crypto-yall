"""Account scope contract tests. No exchange, database, or network calls."""
import copy
import unittest

from offline_account_scope_review import review_account_scope_offline

ACCOUNT = "0x" + ("1" * 40)
OTHER = "0x" + ("2" * 40)

def case():
    scope = dict(
        environment="mainnet", effective_account=ACCOUNT,
        market_type="perp", dex="", coin="SOL",
    )
    return dict(configured=copy.deepcopy(scope),
                intent=copy.deepcopy(scope), snapshot=copy.deepcopy(scope))

class AccountScopeTests(unittest.TestCase):
    def assert_held(self, args, coherent=False):
        result = review_account_scope_offline(**args)
        self.assertEqual(result.status, "hold")
        self.assertEqual(result.structurally_consistent, coherent)
        self.assertFalse(result.submit_authorized)

    def test_exact_synthetic_scope_remains_hold(self):
        self.assert_held(case(), coherent=True)

    def test_mismatched_environment_account_and_coin_hold(self):
        for field, value in (
            ("environment", "testnet"),
            ("effective_account", OTHER),
            ("coin", "BTC"),
            ("market_type", "spot"),
            ("dex", "other"),
        ):
            with self.subTest(field=field):
                data = case()
                data["intent"][field] = value
                self.assert_held(data)

    def test_exchange_snapshot_scope_mismatch_holds(self):
        for field, value in (
            ("environment", "testnet"),
            ("effective_account", OTHER),
            ("coin", "ETH"),
            ("dex", "different"),
        ):
            with self.subTest(field=field):
                data = case()
                data["snapshot"][field] = value
                self.assert_held(data)

    def test_account_scope_is_not_inferred_from_coin_only(self):
        data = case()
        data["intent"] = {"coin": "SOL"}
        self.assert_held(data)

    def test_missing_and_extra_fields_hold(self):
        for target in ("configured", "intent", "snapshot"):
            with self.subTest(target=target):
                data = case()
                del data[target]["effective_account"]
                self.assert_held(data)
                data = case()
                data[target]["wallet"] = ACCOUNT
                self.assert_held(data)

    def test_unknown_dex_or_spot_is_unsupported(self):
        for key, value in (("dex", "nondefault"), ("market_type", "spot")):
            with self.subTest(key=key):
                data = case()
                for source in ("configured", "intent", "snapshot"):
                    data[source][key] = value
                self.assert_held(data)

    def test_invalid_configured_account_rejected(self):
        for bad in ("0x123", "wallet1", "0X" + "1" * 40):
            with self.subTest(bad=bad):
                data = case()
                for source in ("configured", "intent", "snapshot"):
                    data[source]["effective_account"] = bad
                self.assert_held(data)

    def test_missing_pinned_scope_rejected(self):
        data = case()
        data["configured"] = None
        self.assert_held(data)

if __name__ == "__main__":
    unittest.main()
