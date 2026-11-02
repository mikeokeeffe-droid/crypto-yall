"""Fake-provider-only tests for independent, read-only reconciliation."""
import unittest
from offline_independent_entry_reconciler import inspect_unresolved_entry


class IntentReader:
    def __init__(self, intent): self.intent=dict(intent); self.reads=0
    def read_intent(self, **kwargs): self.reads+=1; return dict(self.intent)


class ExchangeReader:
    def __init__(self):
        self.calls=0
        self.order=dict(account="test-account",coin="SOL",order_id="123",
                        final=True,status="rejected",complete=True,filled_size=0)
        self.first=dict(account="test-account",capture_id="first",coin="SOL",
                        fresh=True,complete=True,fills_complete=True,
                        observed_at_ms=95_000,position_size=0,open_orders=[],fills=[])
        self.second=dict(self.first,capture_id="second",observed_at_ms=96_000)
    def read_order(self, **kwargs): self.calls+=1; return dict(self.order)
    def capture_position_orders_fills(self, **kwargs):
        self.calls+=1
        return dict(self.first if self.calls==2 else self.second)


class IndependentReconcilerTests(unittest.TestCase):
    def setUp(self):
        self.intent=dict(bot="daily",coin="SOL",token="test-token",
                         status="uncertain",exchange_order_id="123",
                         submitted_at_ms=90_000,requested_size=0.25)
        self.reader=IntentReader(self.intent)
        self.exchange=ExchangeReader()
    def review(self, **kwargs):
        values=dict(intent_reader=self.reader,exchange_reader=self.exchange,
                    bot="daily",coin="SOL",token="test-token",
                    account="test-account",now_ms=100_000)
        values.update(kwargs)
        return inspect_unresolved_entry(**values)
    def test_valid_fake_evidence_is_review_candidate_only(self):
        self.assertEqual(self.review().status,"review_candidate")
        self.assertEqual(self.reader.reads,2)
        self.assertEqual(self.exchange.calls,3)
    def test_mismatched_intent_prevents_any_exchange_reads(self):
        self.reader.intent["token"]="wrong"
        self.assertEqual(self.review().status,"hold")
        self.assertEqual(self.exchange.calls,0)
    def test_failed_evidence_read_blocks(self):
        self.exchange.read_order=lambda **kwargs: (_ for _ in ()).throw(TimeoutError())
        self.assertEqual(self.review().status,"hold")
    def test_stale_or_future_snapshots_block(self):
        for timestamp in (1,100_001):
            with self.subTest(timestamp=timestamp):
                self.exchange=ExchangeReader()
                self.exchange.first["observed_at_ms"]=timestamp
                self.assertEqual(self.review().status,"hold")
    def test_order_account_and_replayed_capture_block(self):
        for changed in ("account","capture_id"):
            self.exchange=ExchangeReader()
            if changed=="account": self.exchange.order["account"]="other-account"
            else: self.exchange.second["capture_id"]="first"
            self.assertEqual(self.review().status,"hold")
    def test_intent_changed_during_reads_blocks(self):
        class Changing(IntentReader):
            def read_intent(self, **kwargs):
                self.reads+=1
                new=dict(self.intent)
                if self.reads>1: new["exchange_order_id"]="other"
                return new
        self.reader=Changing(self.intent)
        self.assertEqual(self.review().status,"hold")

if __name__=="__main__": unittest.main()
