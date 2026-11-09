"""Offline HMAC envelope negative tests; no real credentials or trading."""
import unittest
from offline_authenticated_envelope_fixture import (
    OfflineAuthenticatedEnvelopeVerifier,sign_fixture_request)

KEY_A=b"a"*32
KEY_B=b"b"*32
INTENT=dict(requested_bot="daily",environment="mainnet",
            account="0x"+"1"*40,dex="",coin="SOL")

class OfflineAuthenticatedEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.verifier=OfflineAuthenticatedEnvelopeVerifier(
            {"daily-principal":KEY_A,"intraday-principal":KEY_B})

    def signed(self,nonce="n1"):
        return sign_fixture_request(KEY_A,"daily-principal","request_entry",INTENT,nonce)

    def test_valid_once_and_replay_denied(self):
        signed=self.signed()
        self.assertEqual(self.verifier.verify(signed),
                         ("daily-principal","request_entry",INTENT))
        self.assertIsNone(self.verifier.verify(signed))

    def test_mutation_and_cross_principal_key_denied(self):
        for field,value in (("operation","request_close"),
                            ("principal","intraday-principal"),
                            ("nonce","other")):
            changed=dict(self.signed())
            changed[field]=value
            self.assertIsNone(self.verifier.verify(changed))
        changed=self.signed()
        changed["intent"]=dict(INTENT,coin="ETH")
        self.assertIsNone(self.verifier.verify(changed))
        wrong=sign_fixture_request(KEY_B,"daily-principal","request_entry",INTENT,"n2")
        self.assertIsNone(self.verifier.verify(wrong))

    def test_malformed_missing_unknown_and_invalid_mac_denied(self):
        for envelope in (None,{},{"principal":"daily-principal"},
                         dict(self.signed(),mac="0"*64),
                         dict(self.signed(),extra="field"),
                         dict(self.signed(),nonce=[]),
                         dict(self.signed(),nonce=""),
                         dict(self.signed(),principal="unknown"),
                         dict(self.signed(),intent={"amount":float("nan")})):
            self.assertIsNone(self.verifier.verify(envelope))

    def test_replay_cache_is_only_in_memory_not_restart_safe(self):
        signed=self.signed()
        self.assertIsNotNone(self.verifier.verify(signed))
        restarted=OfflineAuthenticatedEnvelopeVerifier({"daily-principal":KEY_A})
        self.assertIsNotNone(restarted.verify(signed))
        # Deliberate NO-GO: persistent replay store required.

if __name__=="__main__":
    unittest.main()
