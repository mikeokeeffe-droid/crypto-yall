"""Static, fail-closed check of original bot entry-candidate source shape.

The review-only projector assumes the ORIGINAL Daily/Intraday/Aggressive
candidate dictionaries have exactly six vetted fields. Unlike a test that
constructs a synthetic dict, this inspects all three actual source files
without importing executors, exchange SDKs, credentials or network code.
Any new/renamed candidate key, changed ticker mapping or unexpected entry
action requires manual review before the offline handoff test can pass.

This is not a runtime signer-isolation proof or authorization to dispatch.
"""
import ast
from pathlib import Path
import unittest

from offline_original_signal_projection_ci import _TICKERS, _FIELDS_COMMON

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "daily": "hyperliquid_executor.py",
    "intraday": "intraday_executor.py",
    "aggressive": "aggressive_executor.py",
}
ACTIONS = frozenset(("open_long", "open_short"))


def _top_level_literal_mapping(source, name):
    tree = ast.parse(source)
    assignments = [
        n for n in tree.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == name
                for t in n.targets)
    ]
    if len(assignments) != 1:
        return None
    try:
        return ast.literal_eval(assignments[0].value)
    except (ValueError, TypeError, SyntaxError, RecursionError):
        return None


def _entry_dict_nodes(source):
    """Return candidate entry dicts; unknown AST shapes always fail later."""
    tree = ast.parse(source)
    found = []
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "append"
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id in ("candidates", "open_candidates")
                and len(call.args) == 1
                and isinstance(call.args[0], ast.Dict)):
            continue
        node = call.args[0]
        try:
            keys = [ast.literal_eval(k) for k in node.keys]
        except (ValueError, TypeError, SyntaxError, RecursionError):
            found.append((None, None, None))
            continue
        if not all(type(key) is str for key in keys):
            found.append((None, None, None))
            continue
        pairs = dict(zip(keys, node.values))
        if len(keys) != len(pairs):
            found.append((None, None, None))
            continue
        action = pairs.get("action")
        action_value = (
            action.value
            if isinstance(action, ast.Constant) and type(action.value) is str
            else None
        )
        side = pairs.get("side")
        side_value = (
            side.value
            if isinstance(side, ast.Constant) and type(side.value) is str
            else None
        )
        found.append((set(keys), action_value, side_value))
    return found


class OriginalCandidateSourceContractTests(unittest.TestCase):
    def test_all_original_candidate_dicts_have_exact_reviewed_shape(self):
        for bot, filename in SOURCES.items():
            with self.subTest(bot=bot):
                source = (ROOT / filename).read_text(encoding="utf-8")
                found = _entry_dict_nodes(source)
                self.assertEqual(len(found), 2,
                                 "unreviewed candidate insertion or removal")
                expected_keys = _FIELDS_COMMON | {
                    "confidence" if bot == "daily" else "priority"
                }
                self.assertEqual(
                    {(action, side) for _, action, side in found},
                    {("open_long", "long"), ("open_short", "short")},
                )
                for keys, action, side in found:
                    self.assertEqual(keys, expected_keys)
                    self.assertIn(action, ACTIONS)
                    self.assertEqual(side, "long" if action == "open_long"
                                     else "short")

    def test_original_ticker_maps_equal_strict_review_projection_map(self):
        daily_source = (ROOT / SOURCES["daily"]).read_text(encoding="utf-8")
        intraday_source = (ROOT / "intraday_data_loader.py").read_text(
            encoding="utf-8")
        daily = _top_level_literal_mapping(daily_source, "HL_TICKER_MAP")
        intraday = _top_level_literal_mapping(intraday_source, "HL_SYMBOL_MAP")
        self.assertIsNotNone(daily)
        self.assertEqual(daily, _TICKERS)
        self.assertEqual(intraday, _TICKERS)

    def test_added_field_action_or_missing_candidate_fails_source_contract(self):
        source = (ROOT / SOURCES["daily"]).read_text(encoding="utf-8")
        original = _entry_dict_nodes(source)
        self.assertEqual(len(original), 2)
        altered = source.replace(
            '"action": "open_long",',
            '"action": "open_long", "unexpected_authority": True,',
            1,
        )
        self.assertNotEqual(_entry_dict_nodes(altered), original)
        wrong_action = source.replace(
            '"action": "open_short",',
            '"action": "pyramid_short",',
            1,
        )
        self.assertNotEqual(
            {(action, side) for _, action, side in _entry_dict_nodes(wrong_action)},
            {("open_long", "long"), ("open_short", "short")},
        )
        removed = source.replace(
            'open_candidates.append({',
            'unreviewed_queue.append({',
            1,
        )
        self.assertNotEqual(len(_entry_dict_nodes(removed)), 2)

    def test_never_imports_original_trading_modules(self):
        import sys
        for name in ("hyperliquid_executor", "intraday_executor",
                     "aggressive_executor", "eth_account",
                     "hyperliquid.exchange"):
            self.assertNotIn(name, sys.modules)


if __name__ == "__main__":
    unittest.main()
