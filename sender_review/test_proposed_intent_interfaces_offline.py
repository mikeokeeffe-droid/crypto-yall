"""Offline-only proposed trade intent tests. Absolutely no execution."""
import ast
import json
from pathlib import Path
import unittest

from sender_review.proposed_intent_interfaces_offline import inspect_proposed_intent_offline
from sender_review.request_contract import inspect_sender_entry_request_offline

NONCE="a"*32
REF="b"*32


def body(**changes):
    d={
        "version":1,"action":"open_long","side":"long",
        "coin":"SOL","request_nonce":NONCE,
        "rounded_size":"0.16","requested_leverage":2,
    }
    d.update(changes)
    return json.dumps(d).encode()


def close(**changes):
    d={
        "version":1,"action":"protective_close","side":"long",
        "coin":"SOL","request_nonce":NONCE,"position_ref":REF,
        "close_size":"0.16","observed_position_size":"0.20",
        "exit_reason":"trailing_protection","reduce_only":True,
    }
    d.update(changes)
    return json.dumps(d).encode()


def pyramid(**changes):
    d={
        "version":1,"action":"pyramid_long","side":"long",
        "coin":"SOL","request_nonce":NONCE,"parent_position_ref":REF,
        "rounded_size":"0.02","requested_leverage":2,
    }
    d.update(changes)
    return json.dumps(d).encode()


def leverage(**changes):
    d={
        "version":1,"action":"request_leverage","side":"long",
        "coin":"SOL","request_nonce":NONCE,"parent_position_ref":REF,
        "requested_leverage":2,
    }
    d.update(changes)
    return json.dumps(d).encode()


class ProposedInterfaceTests(unittest.TestCase):
    def assert_no_authority(self,result):
        self.assertFalse(result.identity_authenticated)
        self.assertFalse(result.position_ownership_verified)
        self.assertFalse(result.exchange_snapshot_verified)
        self.assertFalse(result.effective_reduce_only_verified)
        self.assertFalse(result.account_scope_verified)
        self.assertFalse(result.nonce_reserved)
        self.assertFalse(result.request_authorized)
        self.assertFalse(result.submit_authorized)
        self.assertFalse(result.close_authorized)
        self.assertFalse(result.leverage_authorized)
        self.assertFalse(result.signing_enabled)

    def test_each_bot_entry_review_only(self):
        for bot in ("daily","intraday","aggressive"):
            for action,side in (("open_long","long"),("open_short","short")):
                with self.subTest(bot=bot,action=action):
                    review=inspect_proposed_intent_offline(
                        body=body(action=action,side=side),fixture_bot=bot)
                    self.assertEqual(review.state,"parsed_review_only_HOLD")
                    self.assertEqual(review.parsed_action,action)
                    self.assert_no_authority(review)

    def test_aggressive_pyramids_only_and_no_runtime_identity(self):
        for action,side in (("pyramid_long","long"),("pyramid_short","short")):
            for bot in ("daily","intraday","aggressive"):
                review=inspect_proposed_intent_offline(
                    body=pyramid(action=action,side=side),fixture_bot=bot)
                self.assertEqual(review.state,
                    "parsed_review_only_HOLD" if bot=="aggressive" else "hold")
                self.assert_no_authority(review)
        for changes in (
            {"side":"short"}, {"parent_position_ref":""},
            {"requested_leverage":6},{"requested_leverage":True},
            {"account":"0x"+"1"*40},{"reduce_only":True},
            {"rounded_size":"1e3"},
        ):
            with self.subTest(changes=changes):
                review=inspect_proposed_intent_offline(
                    body=pyramid(**changes),fixture_bot="aggressive")
                self.assertEqual(review.state,"hold")
                self.assert_no_authority(review)

    def test_protective_closes_are_only_untrusted_requests(self):
        for bot in ("daily","intraday","aggressive"):
            for why in ("signal_exit","profit_floor","trailing_protection","usd_loss_cap"):
                with self.subTest(bot=bot,why=why):
                    result=inspect_proposed_intent_offline(
                        body=close(exit_reason=why),fixture_bot=bot)
                    self.assertEqual(result.state,"parsed_review_only_HOLD")
                    self.assertEqual(result.parsed_size,"0.16")
                    self.assertTrue(result.requested_reduce_only)
                    self.assert_no_authority(result)
                    self.assertEqual(
                        inspect_sender_entry_request_offline(body=close()).state,
                        "hold")
        for changes in (
            {"close_size":"0"},{"close_size":"-1"},
            {"close_size":"0.21"},{"close_size":"1e2"},
            {"observed_position_size":"0"},
            {"reduce_only":False},{"reduce_only":1},
            {"exit_reason":"unknown"},
            {"position_ref":"0x"+REF},
            {"close_size":0.16},
            {"owner_verified":True},{"account":"0x"+"1"*40},
            {"network":"mainnet"},{"close_size":"0.000000001"},
            {"close_size":"1000001"},
        ):
            with self.subTest(changes=changes):
                result=inspect_proposed_intent_offline(
                    body=close(**changes),fixture_bot="daily")
                self.assertEqual(result.state,"hold")
                self.assert_no_authority(result)

    def test_requested_leverage_cannot_execute(self):
        for bot in ("daily","intraday","aggressive"):
            result=inspect_proposed_intent_offline(
                body=leverage(),fixture_bot=bot)
            self.assertEqual(result.state,"parsed_review_only_HOLD")
            self.assert_no_authority(result)
        for changes in (
            {"requested_leverage":0},{"requested_leverage":6},
            {"requested_leverage":True},{"parent_position_ref":"missing"},
            {"approval":True},{"action":"update_leverage"},
        ):
            with self.subTest(changes=changes):
                result=inspect_proposed_intent_offline(
                    body=leverage(**changes),fixture_bot="intraday")
                self.assertEqual(result.state,"hold")

    def test_invalid_wire_and_untrusted_bot_fail_closed(self):
        for payload in (
            b"",b"bad",b"\xff",b'{"version":1,"version":1}',
            b" "*1025, b'{"x":NaN}'
        ):
            self.assertEqual(inspect_proposed_intent_offline(
                body=payload,fixture_bot="daily").state,"hold")
        for bot in ("unknown",None,1,True,[],{}):
            self.assertEqual(inspect_proposed_intent_offline(
                body=close(),fixture_bot=bot).state,"hold")

    def test_source_has_no_signer_or_network_imports(self):
        source=Path(__file__).with_name(
            "proposed_intent_interfaces_offline.py").read_text("utf-8")
        imports=set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node,ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node,ast.ImportFrom):
                imports.add(node.module)
        self.assertEqual(imports,{
            "dataclasses","decimal","json","re",
            "sender_review.request_contract",
        })


if __name__ == "__main__":
    unittest.main()
