import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class TestGatewayImportSafety(unittest.TestCase):
    def test_no_live_imports_or_order_calls(self):
        tree = ast.parse((ROOT / 'staging_executor_gateway_contract.py').read_text())
        imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        imports += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        self.assertFalse(set(imports) & {'aggressive_executor', 'intraday_executor', 'hyperliquid_executor', 'psycopg', 'requests'})
        calls = [n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        self.assertFalse(set(calls) & {'market_open', 'market_close', 'execute', 'connect'})

if __name__ == '__main__':
    unittest.main()
