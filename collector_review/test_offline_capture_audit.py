"""Offline-only hash chain tests; source and transport remain untrusted."""
from dataclasses import replace
import json
import unittest

from collector_review.testnet_info_https import prepare_testnet_info_body
from collector_review.offline_capture_audit import (
    append_offline_audit_event,
    review_offline_audit_chain,
)

ACCOUNT = "0x" + "1"*40
OTHER = "0x" + "2"*40


def make(*, kind="openOrders", data=b"[]", status=200,
         time=1000, sequence=1, previous=None, account=ACCOUNT):
    return append_offline_audit_event(
        account=account,kind=kind,
        request_body=prepare_testnet_info_body(account=account,kind=kind),
        response_body=data,status_code=status,
        content_type="application/json",content_encoding=None,
        elapsed_ms=100,observed_at_ms=time,sequence=sequence,
        previous=previous,
    )


class OfflineAuditChainTests(unittest.TestCase):
    def test_chain_records_hashes_and_remains_unsigned(self):
        a=make()
        b=make(time=1100,sequence=2,previous=a)
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertEqual(b.previous_sha256,a.event_sha256)
        r=review_offline_audit_chain(events=[a,b],expected_account=ACCOUNT,
                                     expected_head_sha256=b.event_sha256)
        self.assertEqual(r.state,"fixture_only")
        self.assertEqual(r.events,2)
        self.assertEqual(r.last_sha256,b.event_sha256)
        self.assertFalse(r.origin_authenticated)
        self.assertFalse(r.history_complete)
        self.assertFalse(r.ownership_verified)
        self.assertFalse(r.submit_authorized)

    def test_failed_http_is_retained_as_hold(self):
        a=make(status=429,data=b'{"error":"rate limited"}')
        self.assertEqual(a.review_state,"hold")
        r=review_offline_audit_chain(events=[a],expected_account=ACCOUNT)
        self.assertEqual(r.state,"hold")
        self.assertFalse(r.submit_authorized)

    def test_tampering_replay_wrong_scope_gaps_and_head_mismatch_hold(self):
        a=make()
        b=make(time=1100,sequence=2,previous=a)
        for events, scope, head in (
            ([replace(a,response_bytes=999)],ACCOUNT,None),
            ([replace(a,response_sha256="f"*64)],ACCOUNT,None),
            ([replace(a,origin_authenticated=True)],ACCOUNT,None),
            ([a,b],OTHER,None),
            ([b],ACCOUNT,None),
            ([a,a],ACCOUNT,None),
            ([a,b],ACCOUNT,"f"*64),
            ([a,replace(b,previous_sha256="f"*64)],ACCOUNT,None),
        ):
            with self.subTest(events=events,scope=scope):
                r=review_offline_audit_chain(
                    events=events,expected_account=scope,
                    expected_head_sha256=head)
                self.assertEqual(r.state,"hold")
                self.assertFalse(r.submit_authorized)

    def test_builder_refuses_missing_previous_or_out_of_order(self):
        a=make()
        self.assertIsNone(make(sequence=2))
        self.assertIsNone(make(time=1000,sequence=2,previous=a))
        self.assertIsNone(make(time=1100,sequence=3,previous=a))
        self.assertIsNone(make(time=1100,sequence=2,previous=a,account=OTHER))
        self.assertIsNone(make(time=1100,sequence=2,
                               previous=replace(a,request_sha256="f"*64)))
        self.assertIsNone(append_offline_audit_event(
            account=ACCOUNT,kind="market_open",request_body=b"{}",
            response_body=b"[]",status_code=200,content_type="application/json",
            content_encoding=None,elapsed_ms=100,observed_at_ms=1000,sequence=1))

    def test_rejects_invalid_raw_request(self):
        self.assertIsNone(append_offline_audit_event(
            account=ACCOUNT,kind="openOrders",
            request_body=b'{"type":"exchange"}',response_body=b"[]",
            status_code=200,content_type="application/json",
            content_encoding=None,elapsed_ms=100,observed_at_ms=1000,sequence=1))


if __name__=="__main__":
    unittest.main()
