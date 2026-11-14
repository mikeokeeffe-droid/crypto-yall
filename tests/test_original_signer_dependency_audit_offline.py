"""Static baseline: original bots still use a signing-capable client.

This is a CHARACTERIZATION of an open blocker, not a passing deployment
gate. Parse source without importing executors or reading environment
variables. Once a reviewed signer-free cutover is implemented, replace this
baseline with fail-closed tests that prove forbidden signing paths absent.
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOT_FILES = ("hyperliquid_executor.py", "intraday_executor.py",
             "aggressive_executor.py")


def _call_names(tree):
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                names.append(fn.id)
            elif isinstance(fn, ast.Attribute):
                names.append(fn.attr)
    return names


def assess_original_signer_dependency(sources):
    """Return HOLD evidence only; never an authorization."""
    result = {}
    for filename in BOT_FILES:
        data = sources.get(filename)
        if type(data) is not str or not data or len(data) > 500000:
            return {"state": "hold", "reason": "missing or unbounded source"}
        try:
            tree = ast.parse(data, filename=filename)
        except (SyntaxError, ValueError):
            return {"state": "hold", "reason": "unparseable bot source"}
        result[filename] = tree

    daily = result["hyperliquid_executor.py"]
    client = [n for n in daily.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "get_client"]
    if len(client) != 1:
        return {"state": "hold", "reason": "unknown client factory"}

    daily_client = client[0]
    calls = _call_names(daily_client)
    secret_ref = any(
        isinstance(n, ast.Constant) and n.value == "HL_PRIVATE_KEY"
        for n in ast.walk(daily_client)
    )
    if not (secret_ref and "from_key" in calls and "Exchange" in calls):
        return {"state": "hold", "reason": "signer dependency changed; re-audit"}

    for filename, tree in result.items():
        if "get_client" not in _call_names(tree):
            return {"state": "hold", "reason": "bot client dependency changed; re-audit"}
        if filename != "hyperliquid_executor.py":
            imported = any(
                isinstance(n, ast.ImportFrom)
                and n.module == "hyperliquid_executor"
                and any(alias.name == "get_client" for alias in n.names)
                for n in tree.body
            )
            if not imported:
                return {"state": "hold", "reason": "bot import dependency changed; re-audit"}
    return {"state": "hold",
            "reason": "all three bots still depend on signer-backed get_client",
            "signer_dependency_detected": True,
            "signer_free_verified": False,
            "trading_authorized": False}


class OriginalSignerDependencyAudit(unittest.TestCase):
    def test_actual_three_bots_are_not_claimed_signer_free(self):
        sources = {filename: (ROOT / filename).read_text(encoding="utf-8")
                   for filename in BOT_FILES}
        reviewed = assess_original_signer_dependency(sources)
        self.assertEqual(reviewed["state"], "hold")
        self.assertTrue(reviewed.get("signer_dependency_detected"))
        self.assertFalse(reviewed["signer_free_verified"])
        self.assertFalse(reviewed["trading_authorized"])

    def test_unknown_or_changed_paths_fail_closed(self):
        sources = {filename: (ROOT / filename).read_text(encoding="utf-8")
                   for filename in BOT_FILES}
        for bad in (None, "", "not valid python !"):
            altered = dict(sources, **{"hyperliquid_executor.py": bad})
            with self.subTest(bad=bad):
                self.assertEqual(assess_original_signer_dependency(altered)["state"],
                                 "hold")
                self.assertNotIn("signer_dependency_detected",
                                 assess_original_signer_dependency(altered))

    def test_missing_bot_never_grants_authority(self):
        sources = {filename: (ROOT / filename).read_text(encoding="utf-8")
                   for filename in BOT_FILES}
        sources.pop("aggressive_executor.py")
        self.assertEqual(assess_original_signer_dependency(sources)["state"], "hold")
        self.assertNotIn("signer_free_verified", assess_original_signer_dependency(sources))


if __name__ == "__main__":
    unittest.main()
