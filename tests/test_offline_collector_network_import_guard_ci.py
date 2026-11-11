"""CI guard: offline collector modules must not silently gain network/signing.

This is a deliberately narrow static gate for REVIEW-ONLY Python modules.
It is NOT an OS-level egress restriction, proof of absence of all bypasses,
network isolation, source authentication, or safe live trading approval.
A separately scoped real transport requires independent threat review.
"""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROTECTED = (
    "offline_testnet_info_snapshot_plan_ci.py",
    "offline_documented_info_projection_ci.py",
    "offline_signer_free_info_fixture_ci.py",
    "offline_readonly_collector_contract.py",
    "offline_readonly_collector_runner.py",
    "offline_hyperliquid_http_envelope.py",
    "offline_hyperliquid_transport_plan.py",
)

DENIED_IMPORT_ROOTS = frozenset((
    "socket", "ssl", "http", "requests", "urllib3", "httpx",
    "aiohttp", "websocket", "websockets", "hyperliquid",
    "eth_account", "subprocess", "importlib", "ctypes", "ftplib",
))
DENIED_CALLS = frozenset((
    "market_open", "market_close", "update_leverage", "send_order",
    "cancel_order", "sign", "post", "urlopen", "urlretrieve", "urlconnect",
    "connect", "create_connection", "system", "popen",
    "eval", "exec", "__import__", "compile",
))


def analyze_offline_collector_source(source, label):
    """Return static policy violations (does not execute or import code)."""
    tree = ast.parse(source, filename=label)
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in DENIED_IMPORT_ROOTS or root == "urllib":
                    violations.append((node.lineno, "import", alias.name))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".")[0]
            # The URL parser in the existing transport-policy helper performs
            # no network request; all other urllib modules are prohibited.
            if (root in DENIED_IMPORT_ROOTS
                    or root == "urllib" and module != "urllib.parse"):
                violations.append((node.lineno, "from", module))
            if module == "urllib.parse":
                for alias in node.names:
                    if alias.name != "urlsplit":
                        violations.append((node.lineno, "urllib.parse", alias.name))
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (
                fn.attr if isinstance(fn, ast.Attribute) else ""
            )
            if name.lower() in DENIED_CALLS:
                violations.append((node.lineno, "call", name))
    return violations


class OfflineCollectorNoNetworkImportGuard(unittest.TestCase):
    def test_all_seven_offline_collector_modules_remain_network_free(self):
        for path in PROTECTED:
            with self.subTest(path=path):
                source = (ROOT / path).read_text(encoding="utf-8")
                violations = analyze_offline_collector_source(source, path)
                self.assertEqual(violations, [], f"{path}: {violations}")

    def test_guard_catches_network_signing_dynamic_import_and_order_calls(self):
        examples = (
            "import requests",
            "from urllib.request import urlopen",
            "import socket",
            "from hyperliquid.exchange import Exchange",
            "import importlib",
            "import subprocess",
            "market_open('SOL', True, 0.1)",
            "client.market_close('SOL')",
            "exchange.update_leverage(2, 'SOL', True)",
            "exec('pass')",
            "__import__('requests')",
            "from urllib.parse import urljoin",
        )
        for source in examples:
            with self.subTest(source=source):
                self.assertTrue(
                    analyze_offline_collector_source(source, "probe"),
                    source,
                )
        self.assertEqual(analyze_offline_collector_source(
            "from urllib.parse import urlsplit", "allowed_parser",
        ), [])


if __name__ == "__main__":
    unittest.main()
