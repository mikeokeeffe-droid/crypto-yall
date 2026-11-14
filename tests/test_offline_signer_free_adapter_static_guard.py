"""Static guard for review-only, signer-free original bot adapters.

Checks the two pure offline modules used by CI's synthetic input/entry
handoff. Does NOT prove actual original executors are signer-free, OS-level
credential absence, real exchange provenance, or safe deployment.
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROTECTED = ("offline_original_bot_intent_adapter.py",
             "offline_signer_free_info_fixture_ci.py",
             "offline_signer_free_bot_view_ci.py",
             "offline_three_bot_mutation_review_ci.py")
DENIED_MODULES = frozenset({
    "hyperliquid", "eth_account", "requests", "socket", "ssl", "http",
    "urllib", "urllib3", "httpx", "aiohttp", "websocket", "websockets",
    "subprocess", "ctypes", "importlib", "ftplib", "pathlib_not_used",
})
DENIED_CALLS = frozenset({
    "Exchange", "from_key", "market_open", "market_close",
    "update_leverage", "send_order", "cancel_order", "connect", "post",
    "urlopen", "getenv", "__import__", "eval", "exec", "system", "popen",
})


def static_signer_free_violations(source):
    """Conservative AST checks on explicitly scoped review-only modules."""
    tree = ast.parse(source)
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in DENIED_MODULES:
                    violations.append("import:" + alias.name)
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in DENIED_MODULES:
                violations.append("from:" + (node.module or ""))
        elif isinstance(node, ast.Call):
            func = node.func
            name = (func.id if isinstance(func, ast.Name)
                    else func.attr if isinstance(func, ast.Attribute)
                    else None)
            if name in DENIED_CALLS:
                violations.append("call:" + name)
        elif isinstance(node, ast.Attribute):
            if node.attr == "environ":
                violations.append("attribute:environ")
        elif isinstance(node, ast.Constant):
            if (type(node.value) is str and node.value in {
                "HL_PRIVATE_KEY", "HL_ACCOUNT_ADDRESS", "HL_TESTNET",
            }):
                violations.append("credential-key-reference")
    return violations


class SignerFreeOfflineAdapterStaticGuard(unittest.TestCase):
    def test_review_only_adapter_modules_remain_signer_free(self):
        for path in PROTECTED:
            with self.subTest(path=path):
                source = (ROOT / path).read_text(encoding="utf-8")
                self.assertEqual(static_signer_free_violations(source), [])

    def test_guard_rejects_obvious_signing_network_and_env_access(self):
        candidates = (
            "from hyperliquid.exchange import Exchange",
            "import requests",
            "import socket",
            "from eth_account import Account",
            "exchange.market_open('SOL', True, 1)",
            "exchange.market_close('SOL')",
            "wallet = Account.from_key('test')",
            "import os\nkey = os.environ.get('PRIVATE_KEY')",
            "import os\nkey = os.getenv('HL_PRIVATE_KEY')",
            "def f():\n return __import__('requests')",
        )
        for source in candidates:
            with self.subTest(source=source):
                self.assertTrue(static_signer_free_violations(source))


if __name__ == "__main__":
    unittest.main()
