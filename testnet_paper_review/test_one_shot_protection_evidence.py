"""Temporary-fixture-only test of TESTNET persistent bracket evidence.

Uses no actual signer, network or production state files. A write-once intent
survives restart but cannot be mistaken for an exchange ACK or trade approval.
"""
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest

import testnet_paper_review.one_shot_protection_evidence as evidence
from testnet_paper_review.test_offline_signer_boundary import valid
from testnet_paper_review.offline_client_order_bundle import build_offline_client_order_bundle


def fixture():
    args=valid()
    bundle=build_offline_client_order_bundle(**args)
    return args["plan"],bundle


def response(bundle):
    return {"status":"ok","response":{"data":{"statuses":[
        {"filled":{"oid":101,"totalSz":bundle.orders[0]["sz"]}},
        {"resting":{"oid":102}},
        {"resting":{"oid":103}}
    ]}}}


class WriteOnceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="testnet-evidence-")
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        os.chmod(self.root,0o700)
        p=patch.object(evidence,"ROOT",str(self.root))
        p.start()
        self.addCleanup(p.stop)

    def test_prepared_then_ack_restart_proves_no_order_permission(self):
        plan,bundle=fixture()
        witness=evidence.WriteOnceProtectionEvidence()
        self.assertIn("BEFORE_ORDER",witness.prepare_before_order(plan=plan,bundle=bundle))
        stored=witness.read_restart_state()
        self.assertFalse(stored.ack_present)
        self.assertIsNone(stored.response)
        self.assertFalse(stored.may_trade)
        with self.assertRaises(evidence.EvidenceHold):
            witness.prepare_before_order(plan=plan,bundle=bundle)
        self.assertIn("ACK_DURABLE",witness.write_exact_ack(
            bundle=bundle,response=response(bundle)
        ))
        after=evidence.WriteOnceProtectionEvidence().read_restart_state()
        self.assertTrue(after.ack_present)
        self.assertFalse(after.may_trade)
        self.assertEqual(after.response,response(bundle))
        with self.assertRaises(evidence.EvidenceHold):
            witness.write_exact_ack(bundle=bundle,response=response(bundle))
        self.assertEqual(len(list(self.root.iterdir())),2)

    def test_unknown_or_partial_ack_never_writes_ack_file(self):
        plan,bundle=fixture()
        w=evidence.WriteOnceProtectionEvidence()
        w.prepare_before_order(plan=plan,bundle=bundle)
        for ack in (None,{},{"status":"err"},
                    {"status":"ok","response":{"data":{"statuses":[]}}},
                    {"status":"ok","response":{"data":{"statuses":[
                        {"filled":{"oid":101,"totalSz":"0.001"}},
                        {"resting":{"oid":102}},{"resting":{"oid":103}}
                    ]}}}):
            with self.subTest(ack=ack),self.assertRaises(evidence.EvidenceHold):
                w.write_exact_ack(bundle=bundle,response=ack)
        self.assertFalse((self.root/evidence.ACK).exists())
        self.assertFalse(w.read_restart_state().ack_present)

    def test_corrupted_prepared_refuses_ack_and_restart(self):
        plan,bundle=fixture()
        w=evidence.WriteOnceProtectionEvidence()
        w.prepare_before_order(plan=plan,bundle=bundle)
        p=self.root/evidence.PREPARED
        raw=json.loads(p.read_bytes())
        raw["payload"]["bundle"]["account"]="0x"+"0"*40
        p.write_text(json.dumps(raw))
        with self.assertRaises(evidence.EvidenceHold):
            w.read_restart_state()
        with self.assertRaises(evidence.EvidenceHold):
            w.write_exact_ack(bundle=bundle,response=response(bundle))

    def test_original_daily_only_long_sends_nothing(self):
        plan,bundle=fixture()
        from dataclasses import replace
        with self.assertRaises(evidence.EvidenceHold):
            evidence.WriteOnceProtectionEvidence().prepare_before_order(
                plan=replace(plan,direction="short"),bundle=bundle
            )
        self.assertFalse(list(self.root.iterdir()))

    def test_private_dir_and_missing_prepared_fail_closed(self):
        w=evidence.WriteOnceProtectionEvidence()
        with self.assertRaises(evidence.EvidenceHold):
            w.read_restart_state()
        os.chmod(self.root,0o755)
        with self.assertRaises(evidence.EvidenceHold):
            evidence.WriteOnceProtectionEvidence()

    def test_no_signers_http_or_trade_entrypoint(self):
        import ast
        tree=ast.parse(Path(evidence.__file__).read_text())
        imported={n.module for n in ast.walk(tree)
                  if isinstance(n,ast.ImportFrom) and n.module}
        self.assertFalse(any(n.startswith(("eth_account","hyperliquid.exchange"))
                             for n in imported))
        method_names={n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
        self.assertFalse({"main","send_once","place_order","market_open",
                          "bulk_orders","market_close","update_leverage"} & method_names)

if __name__=="__main__":
    unittest.main()
