"""Synthetic API JSON tests; no network, wallet, signing or order actions."""
from dataclasses import replace
import ast
import json
from pathlib import Path
import unittest

from sender_review.hyperliquid_readonly_collection_plan_offline import (
    plan_offline_readonly_testnet_collection,
)
from sender_review.mock_hyperliquid_info_collector_offline import (
    MockInfoReply, ScriptedMockInfoTransport,
    inspect_scripted_info_collection_offline,
)

ACCOUNT = "0x" + "1" * 40
CLOID = "0x" + "b" * 32
OID = 123
TID = 456


def make_plan(*, with_lookup=False):
    return plan_offline_readonly_testnet_collection(
        account=ACCOUNT, start_time_ms=1000, end_time_ms=2000,
        optional_order_lookup=CLOID if with_lookup else None,
    )


def order_doc(**changes):
    d = dict(oid=OID, coin="SOL", side="B", origSz="0.20",
             cloid=CLOID, timestamp=1200)
    d.update(changes)
    return d


def baseline_docs(*, with_lookup=False):
    position = {"assetPositions": [{"position": {"coin": "SOL", "szi": "0.20"}}]}
    order = {"status": "filled", "order": order_doc()}
    fill = {"oid": OID, "tid": TID, "coin": "SOL",
            "side": "B", "sz": "0.20", "time": 1250}
    docs = [position, [], [order], [fill], position]
    if with_lookup:
        docs.insert(4, {"status": "order", "order": order})
    return docs


def simulate(*, docs=None, with_lookup=False, replies=None, plan=None):
    plan = plan or make_plan(with_lookup=with_lookup)
    docs = baseline_docs(with_lookup=with_lookup) if docs is None else docs
    if replies is None:
        replies = tuple(
            MockInfoReply(q.body_json, 200, json.dumps(d).encode())
            for q, d in zip(plan.queries, docs)
        )
    return inspect_scripted_info_collection_offline(
        plan=plan, transport=ScriptedMockInfoTransport(replies=replies)
    )


class OfflineMockCollectorTests(unittest.TestCase):
    def assert_no_authority(self, result):
        self.assertEqual(result.state, "HOLD")
        for field in (
            "history_complete", "provider_authenticated",
            "account_ownership_verified", "runtime_identity_authenticated",
            "network_request_performed", "exchange_order_permitted",
            "close_authorized", "retry_authorized", "signing_enabled",
        ):
            self.assertFalse(getattr(result, field), field)

    def test_coherent_synthetic_responses_still_hold(self):
        for lookup in (False, True):
            with self.subTest(lookup=lookup):
                result = simulate(with_lookup=lookup)
                self.assertTrue(result.fixture_consistent)
                self.assertEqual(dict(result.fixture_counts), {
                    "positions": 1, "historicalOrders": 1,
                    "userFillsByTime": 1,
                })
                self.assert_no_authority(result)

    def test_malformed_json_and_duplicate_keys_are_held(self):
        plan = make_plan()
        valid = [
            MockInfoReply(q.body_json, 200, json.dumps(d).encode())
            for q, d in zip(plan.queries, baseline_docs())
        ]
        for body in (
            b"not-json", b"{}", b"\xff", b'{"assetPositions":[],"assetPositions":[]}',
            b'{"assetPositions":NaN}', b"", b"x" * 262145,
        ):
            with self.subTest(body=body[:30]):
                changed = list(valid)
                changed[0] = replace(changed[0], body=body)
                result = simulate(replies=tuple(changed))
                self.assertFalse(result.fixture_consistent)
                self.assert_no_authority(result)

    def test_http_failure_and_response_mismatch_hold(self):
        plan = make_plan()
        valid = [
            MockInfoReply(q.body_json, 200, json.dumps(d).encode())
            for q, d in zip(plan.queries, baseline_docs())
        ]
        cases = (
            replace(valid[0], status_code=500),
            replace(valid[0], status_code=True),
            replace(valid[0], request_body_json="{}"),
        )
        for bad in cases:
            replies = list(valid)
            replies[0] = bad
            result = simulate(replies=tuple(replies))
            self.assertFalse(result.fixture_consistent)
            self.assert_no_authority(result)
        for replies in (tuple(valid[:-1]), tuple(valid + [valid[-1]])):
            self.assertFalse(simulate(replies=replies).fixture_consistent)

    def test_untrusted_transport_activation_and_unknown_shapes_hold(self):
        plan = make_plan()
        replies = tuple(
            MockInfoReply(q.body_json, 200, json.dumps(d).encode())
            for q, d in zip(plan.queries, baseline_docs())
        )
        for transport in (
            ScriptedMockInfoTransport(replies, network_enabled=True),
            ScriptedMockInfoTransport(replies, exchange_calls=1),
            ScriptedMockInfoTransport(replies[:-1]),
        ):
            result = inspect_scripted_info_collection_offline(
                plan=plan, transport=transport
            )
            self.assertFalse(result.fixture_consistent)
            self.assert_no_authority(result)

    def test_positions_mutation_bad_sizes_duplicate_coins_hold(self):
        for changes in (
            {"szi": "NaN"}, {"szi": "1e2"}, {"szi": "0.19"},
            {"coin": "sol"}, {"szi": True},
        ):
            docs = baseline_docs()
            docs[4] = {"assetPositions": [
                {"position": dict(docs[0]["assetPositions"][0]["position"], **changes)}
            ]}
            result = simulate(docs=docs)
            self.assertFalse(result.fixture_consistent)
            self.assert_no_authority(result)
        docs = baseline_docs()
        docs[0] = {"assetPositions": [
            {"position": {"coin": "SOL", "szi": "0.20"}},
            {"position": {"coin": "SOL", "szi": "0.20"}},
        ]}
        self.assertFalse(simulate(docs=docs).fixture_consistent)

    def test_open_or_unknown_orders_and_retention_cap_hold(self):
        docs = baseline_docs()
        docs[1] = [dict(oid=222, coin="SOL", side="A",
                        sz="0.10", timestamp=1400)]
        self.assertFalse(simulate(docs=docs).fixture_consistent)
        docs = baseline_docs()
        docs[2][0]["status"] = "open"
        self.assertFalse(simulate(docs=docs).fixture_consistent)
        docs = baseline_docs()
        docs[2] = docs[2] * 2000
        cap_result = simulate(docs=docs)
        self.assertFalse(cap_result.fixture_consistent)
        self.assert_no_authority(cap_result)
        # A large JSON body may hit the byte limit before the history cap.
        self.assertTrue(
            "cap" in cap_result.reason or "malformed" in cap_result.reason
        )
        docs = baseline_docs()
        docs[3] = docs[3] * 2000
        self.assertFalse(simulate(docs=docs).fixture_consistent)

    def test_conflicting_ids_fills_and_position_amounts_hold(self):
        cases = []
        d = baseline_docs()
        d[3] = [dict(d[3][0], oid=999)]
        cases.append(d)
        d = baseline_docs()
        d[3] = [d[3][0], d[3][0]]
        cases.append(d)
        d = baseline_docs()
        d[3][0]["sz"] = "0.25"
        cases.append(d)
        d = baseline_docs()
        d[3][0]["side"] = "A"
        cases.append(d)
        d = baseline_docs()
        d[3][0]["time"] = 900
        cases.append(d)
        d = baseline_docs()
        d[2].append(dict(d[2][0]))
        cases.append(d)
        d = baseline_docs()
        d[2][0]["order"]["origSz"] = "0.30"
        cases.append(d)
        for docs in cases:
            with self.subTest(docs=docs):
                result = simulate(docs=docs)
                self.assertFalse(result.fixture_consistent)
                self.assert_no_authority(result)

    def test_order_status_wrong_cloid_or_oid_hold(self):
        d = baseline_docs(with_lookup=True)
        d[4]["order"]["order"]["cloid"] = "0x" + "a" * 32
        result = simulate(docs=d, with_lookup=True)
        self.assertFalse(result.fixture_consistent)
        self.assert_no_authority(result)
        d = baseline_docs(with_lookup=True)
        d[4]["order"]["status"] = "open"
        self.assertFalse(simulate(docs=d, with_lookup=True).fixture_consistent)

    def test_mutated_request_plan_cannot_impersonate_safe_info_read(self):
        base = make_plan()
        mutations = (
            (0, '{"type":"clearinghouseState","user":"0x' + '2'*40 + '","dex":""}'),
            (0, '{"type":"clearinghouseState","user":"0x' + '1'*40 + '","dex":"evil"}'),
            (0, '{"type":"exchange","user":"0x' + '1'*40 + '"}'),
            (0, '{"type":"clearinghouseState","user":"0x' + '1'*40 +
                '","dex":"","submitAuthorized":true}'),
            (3, '{"type":"userFillsByTime","user":"0x' + '1'*40 +
                '","startTime":0,"endTime":2000,"aggregateByTime":false}'),
        )
        for index, altered in mutations:
            with self.subTest(index=index, altered=altered):
                queries = list(base.queries)
                queries[index] = replace(queries[index], body_json=altered)
                modified = replace(base, queries=tuple(queries))
                result = simulate(plan=modified)
                self.assertFalse(result.fixture_consistent)
                self.assert_no_authority(result)

    def test_altered_request_transport_and_privileges_hold(self):
        base = make_plan()
        q = base.queries[0]
        for item in (
            replace(q, host="evil.example"),
            replace(q, path="/exchange"),
            replace(q, method="GET"),
            replace(q, contains_trading_key=True),
            replace(q, network_request_performed=True),
            replace(q, authorizes_order=True),
            replace(q, body_json='{"type":"clearinghouseState"}'),
        ):
            with self.subTest(item=item):
                queries = (item,) + base.queries[1:]
                result = simulate(plan=replace(base, queries=queries))
                self.assertFalse(result.fixture_consistent)
                self.assert_no_authority(result)

    def test_mock_collector_has_no_dynamic_io_or_signing_calls(self):
        src = Path(__file__).with_name(
            "mock_hyperliquid_info_collector_offline.py").read_text("utf-8")
        tree = ast.parse(src)
        forbidden = {
            "open", "exec", "eval", "__import__",
            "getattr", "setattr", "delattr",
            "system", "popen", "run", "Popen",
            "urlopen", "request", "post",
            "connect", "socket", "Exchange",
            "market_open", "market_close", "order",
            "update_leverage", "cancel",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = (
                    node.func.id if isinstance(node.func, ast.Name)
                    else node.func.attr if isinstance(node.func, ast.Attribute)
                    else ""
                )
                with self.subTest(name=name, line=node.lineno):
                    self.assertNotIn(name, forbidden)
                    if isinstance(node.func, ast.Name):
                        self.assertNotEqual(name, "compile")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in (
                    node.names if isinstance(node, ast.Import)
                    else [type("X", (), {"name": node.module})()]
                ):
                    self.assertNotIn(alias.name.split(".")[0], {
                        "os", "sys", "subprocess", "socket", "http",
                        "urllib", "requests", "httpx", "aiohttp",
                        "eth_account", "hyperliquid", "psycopg",
                        "importlib", "pathlib",
                    })

    def test_imports_are_pure_parsing_only(self):
        path = Path(__file__).with_name("mock_hyperliquid_info_collector_offline.py")
        imported = set()
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module)
        self.assertEqual(imported, {
            "dataclasses", "decimal", "json", "re",
            "sender_review.hyperliquid_readonly_collection_plan_offline",
        })


if __name__ == "__main__":
    unittest.main()
