"""Static regression guard for the five inert review-only network entrypoints.

These checks are deliberately NARROW: they prevent an accidental future
Boolean-activated HTTP helper from being added to the draft PR without
triggering a reviewed change. They do not establish runtime host isolation,
network egress restrictions, trading authorization, or general code safety.
"""
import ast
from pathlib import Path
import unittest

_ROOT = Path(__file__).resolve().parent
_REVIEWED = {
    "coordinated_testnet_readset_review.py": (
        "inspect_coordinated_testnet_readset_transport_review",
        "CoordinatedReadsetReview",
        frozenset({
            "dataclasses", "decimal", "hashlib", "json",
            "sender_review.hyperliquid_testnet_readonly_snapshot_review",
            "sender_review.hyperliquid_testnet_recent_history_review",
        }),
    ),
    "hyperliquid_testnet_readonly_snapshot_review.py": (
        "inspect_testnet_info_readonly_snapshot",
        "ReadOnlyTestnetSnapshot",
        frozenset({"dataclasses", "decimal", "re"}),
    ),
    "hyperliquid_testnet_recent_history_review.py": (
        "inspect_testnet_recent_history_review",
        "RecentHistoryReview",
        frozenset({
            "dataclasses", "decimal", "re",
            "sender_review.hyperliquid_testnet_readonly_snapshot_review",
        }),
    ),
    "github_oidc_public_keys_transport_review.py": (
        "review_github_public_jwks_transport",
        "GithubPublicKeysTransportReview",
        frozenset({
            "dataclasses", "json",
            "sender_review.oidc_jwks_keyset_offline",
        }),
    ),
    "github_runner_oidc_handoff_review.py": (
        "request_runner_oidc_token_review",
        "RunnerOidcHandoffReview",
        frozenset({"dataclasses", "re", "urllib.parse"}),
    ),
}


def _verify_file(path, function_name, return_class, allowed_imports):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    matches = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    ]
    if len(matches) != 1 or isinstance(matches[0], ast.AsyncFunctionDef):
        raise ValueError(f"{path.name}: entrypoint absent or asynchronous")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports = [entry.name for entry in node.names]
        elif isinstance(node, ast.ImportFrom):
            imports = [node.module]
        else:
            continue
        if any(name not in allowed_imports for name in imports):
            raise ValueError(f"{path.name}: module import outside inert allowlist: {imports}")
    fn = matches[0]
    # A pure docstring followed by exactly one result-constructor return.
    # Prevent Boolean-gated branches and hidden network calls creeping in.
    statements = fn.body[:]
    if (statements and isinstance(statements[0], ast.Expr)
            and isinstance(statements[0].value, ast.Constant)
            and isinstance(statements[0].value.value, str)):
        statements = statements[1:]
    if len(statements) != 1 or not isinstance(statements[0], ast.Return):
        raise ValueError(f"{path.name}: entrypoint no longer a single HOLD return")
    returned = statements[0].value
    if (not isinstance(returned, ast.Call)
            or not isinstance(returned.func, ast.Name)
            or returned.func.id != return_class
            or returned.args
            or any(kw.arg not in ("reason",) or
                   not isinstance(kw.value, ast.Constant) or
                   not isinstance(kw.value.value, str)
                   for kw in returned.keywords)):
        raise ValueError(f"{path.name}: entrypoint must return inert {return_class}")


class ReviewOnlyNetworkImportGuard(unittest.TestCase):
    def test_five_entrypoints_remain_inert_and_imports_are_allowlisted(self):
        self.assertEqual(len(_REVIEWED), 5)
        for filename, (function, result, allowed) in _REVIEWED.items():
            with self.subTest(module=filename):
                _verify_file(_ROOT / filename, function, result, allowed)

    def test_guard_catches_unapproved_network_import(self):
        source = "import urllib.request\n" + (_ROOT / (
            "hyperliquid_testnet_readonly_snapshot_review.py"
        )).read_text(encoding="utf-8")
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hyperliquid_testnet_readonly_snapshot_review.py"
            path.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "import outside inert allowlist"):
                _verify_file(path, *_REVIEWED[path.name])

    def test_guard_catches_true_flag_conditional_network_opt_in(self):
        source_path = _ROOT / "github_runner_oidc_handoff_review.py"
        source = source_path.read_text(encoding="utf-8")
        source = source.replace(
            "    return RunnerOidcHandoffReview()",
            "    if explicitly_enabled:\n"
            "        return RunnerOidcHandoffReview()\n"
            "    return RunnerOidcHandoffReview()",
        )
        self.assertNotEqual(source, source_path.read_text(encoding="utf-8"))
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / source_path.name
            path.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "single HOLD return"):
                _verify_file(path, *_REVIEWED[path.name])


if __name__ == "__main__":
    unittest.main()
