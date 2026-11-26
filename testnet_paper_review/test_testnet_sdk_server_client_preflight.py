"""Offline SDK Testnet client binding checks; never open the signer file."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import ast
import unittest

from testnet_paper_review.testnet_sdk_server_client_preflight import (
    AGENT_ADDRESS, KEY_PATH, ClientPreflight, SignerSDKHold, inspect_sdk_client,
    load_local_agent, main
)
from testnet_paper_review.offline_order_guard import TESTNET_ACCOUNT, TESTNET_ENDPOINT


class MockInfo:
    base_url=TESTNET_ENDPOINT
    def name_to_asset(self, name):
        if name != "SOL":raise AssertionError("unexpected asset")
        return 5


class MockExchange:
    def __init__(self, wallet, *, base_url, account_address, timeout):
        self.base_url=base_url
        self.account_address=account_address
        self.wallet=wallet
        self.vault_address=None
        self.info=MockInfo()


class ClientPreflightTests(unittest.TestCase):
    def test_pinned_wallet_and_sol_sdk_mapping_no_send(self):
        result=inspect_sdk_client(
            wallet=SimpleNamespace(address=AGENT_ADDRESS),
            exchange_factory=MockExchange
        )
        self.assertIsInstance(result,ClientPreflight)
        self.assertEqual(result.sol_asset_id,5)
        self.assertFalse(result.may_send)
        self.assertEqual(result.testnet_endpoint,TESTNET_ENDPOINT)
        self.assertEqual(result.owner,TESTNET_ACCOUNT)

    def test_wrong_wallet_rejected_before_exchange(self):
        class Forbidden:
            def __init__(self,*a,**k):
                raise AssertionError("should not instantiate SDK")
        with self.assertRaises(SignerSDKHold):
            inspect_sdk_client(wallet=SimpleNamespace(address=TESTNET_ACCOUNT),
                               exchange_factory=Forbidden)

    def test_mainnet_factory_and_foreign_owner_rejected(self):
        class Mainnet(MockExchange):
            def __init__(self,*a,**k):
                super().__init__(*a,**k)
                self.base_url="https://api.hyperliquid.xyz"
        class Foreign(MockExchange):
            def __init__(self,*a,**k):
                super().__init__(*a,**k)
                self.account_address="0x"+"0"*40
        for exchange in (Mainnet, Foreign):
            with self.subTest(exchange=exchange),self.assertRaises(SignerSDKHold):
                inspect_sdk_client(wallet=SimpleNamespace(address=AGENT_ADDRESS),
                                   exchange_factory=exchange)

    def test_deny_unknown_asset(self):
        class Bad(MockExchange):
            def __init__(self,*a,**k):
                super().__init__(*a,**k)
                self.info.name_to_asset=lambda name:10001
        with self.assertRaises(SignerSDKHold):
            inspect_sdk_client(wallet=SimpleNamespace(address=AGENT_ADDRESS),
                               exchange_factory=Bad)

    def test_no_key_or_transport_calls_in_ci(self):
        import testnet_paper_review.testnet_sdk_server_client_preflight as mod
        tree=ast.parse(Path(mod.__file__).read_text())
        names={n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
        self.assertNotIn("place_order",names)
        self.assertNotIn("bulk_orders",names)
        self.assertEqual(main([]),2)
        with self.assertRaises(SignerSDKHold):
            load_local_agent(key_path="/tmp/untrusted-key")

if __name__=="__main__":
    unittest.main()
