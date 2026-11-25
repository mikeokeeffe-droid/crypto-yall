"""Disposable, offline-only SQLite crash/restart and concurrency tests."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from testnet_paper_review.offline_order_guard import HoldError, REVIEW_WRITER
from testnet_paper_review.offline_durable_restart_journal import (
    DisposableReviewJournal, FILENAME, TMP_PREFIX,
)
from testnet_paper_review.test_offline_order_guard import NOW, good_intent, good_snapshot


class DurableOfflineReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix=TMP_PREFIX)
        self.path = Path(self.tmp.name) / FILENAME

    def tearDown(self):
        self.tmp.cleanup()

    def test_restart_keeps_original_claim(self):
        with DisposableReviewJournal(self.path) as j:
            self.assertIn("HOLD", j.stage(good_intent(), good_snapshot(), now_s=NOW, writer_id=REVIEW_WRITER))
            self.assertEqual(j.view()[-1], "STAGED_HOLD")
        with DisposableReviewJournal(self.path) as restarted:
            self.assertEqual(restarted.view()[0], good_intent().request_id)
            with self.assertRaises(HoldError):
                restarted.stage(replace(good_intent(), request_id="review-unique-2222"),
                                good_snapshot(), now_s=NOW, writer_id=REVIEW_WRITER)

    def test_restart_unknown_ack_then_reconcile_still_no_retry(self):
        with DisposableReviewJournal(self.path) as j:
            j.stage(good_intent(), good_snapshot(), now_s=NOW, writer_id=REVIEW_WRITER)
            j.simulated_ack(good_intent().request_id, "unknown")
        with DisposableReviewJournal(self.path) as restarted:
            self.assertEqual(restarted.view()[-1], "UNKNOWN_ACK_HOLD")
            self.assertIn("HOLD", restarted.reconcile_fixture(good_intent().request_id,
                                                               evidence_fresh=True, exact_match=True))
            self.assertEqual(restarted.view()[-1], "RECONCILED_HOLD")
        with DisposableReviewJournal(self.path) as restarted:
            with self.assertRaises(HoldError):
                restarted.stage(replace(good_intent(), request_id="review-unique-3333"),
                                good_snapshot(), now_s=NOW, writer_id=REVIEW_WRITER)
            with self.assertRaises(HoldError):
                restarted.simulated_ack(good_intent().request_id, "filled")

    def test_ambiguous_reconciliation_is_permanent_hold(self):
        with DisposableReviewJournal(self.path) as j:
            j.stage(good_intent(),good_snapshot(),now_s=NOW,writer_id=REVIEW_WRITER)
            j.simulated_ack(good_intent().request_id,"unknown")
        with DisposableReviewJournal(self.path) as j:
            j.reconcile_fixture(good_intent().request_id,evidence_fresh=False,exact_match=True)
            self.assertEqual(j.view()[-1],"UNRESOLVED_HOLD")
        with DisposableReviewJournal(self.path) as j:
            with self.assertRaises(HoldError):
                j.reconcile_fixture(good_intent().request_id,evidence_fresh=True,exact_match=True)

    def test_competing_concurrent_writers_only_one_claims(self):
        def compete(n):
            try:
                with DisposableReviewJournal(self.path) as j:
                    j.stage(replace(good_intent(),request_id=f"review-claim-{n:04}"),
                            good_snapshot(),now_s=NOW,writer_id=REVIEW_WRITER)
                return True
            except HoldError:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(compete, range(8)))
        self.assertEqual(sum(results),1)
        with DisposableReviewJournal(self.path) as j:
            self.assertEqual(j.view()[-1],"STAGED_HOLD")

    def test_wrong_writer_and_wrong_account_rejected(self):
        with DisposableReviewJournal(self.path) as j:
            with self.assertRaises(HoldError):
                j.stage(good_intent(), good_snapshot(), now_s=NOW, writer_id="aggressive")
            with self.assertRaises(HoldError):
                j.stage(replace(good_intent(),account="0x"+"0"*40),
                        good_snapshot(),now_s=NOW,writer_id=REVIEW_WRITER)
            self.assertIsNone(j.view())

    def test_invalid_paths_rejected(self):
        for path in (Path("review-only.sqlite3"), Path(tempfile.gettempdir())/"review-only.sqlite3",
                     Path(self.tmp.name)/"production.sqlite3"):
            with self.subTest(path=str(path)), self.assertRaises(HoldError):
                DisposableReviewJournal(path)

    def test_no_order_execution_surface(self):
        import ast
        import testnet_paper_review.offline_durable_restart_journal as mod
        tree=ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
        forbidden={"hyperliquid","requests","urllib","socket","subprocess","eth_account"}
        imports={n.module.split(".")[0] for n in ast.walk(tree)
                 if isinstance(n,ast.ImportFrom) and n.module}
        imports|={a.name.split(".")[0] for n in ast.walk(tree)
                  if isinstance(n,ast.Import) for a in n.names}
        self.assertFalse(forbidden.intersection(imports))
        methods={n.name for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
        self.assertFalse({"place_order","submit_order","market_open","market_close","execute_trade","main"}.intersection(methods))

if __name__ == "__main__":
    unittest.main()
