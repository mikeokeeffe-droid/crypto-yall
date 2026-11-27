"""Public TESTNET API agent review tests; no signing or order submission."""
import unittest
from testnet_paper_review.testnet_public_agent_review import (
    read_public_agents,review_public_agents,AgentHold
)
from testnet_paper_review.testnet_daily_admission_gate import EXPECTED_ACCOUNT
A="0x1234567890abcdef1234567890ABCDEF12345678"

class PublicAgentTests(unittest.TestCase):
    def test_matching_live_agent_still_no_trade(self):
        def fetch(kind,user):
            if kind=="extraAgents":
                return [{"address":A,"validUntil":2000000000000}]
            return {"role":"agent","data":{"user":EXPECTED_ACCOUNT}}
        x=review_public_agents(fetcher=fetch,clock=lambda:1800000000000)
        self.assertEqual(x["active_named_owner_agents"],1)
        self.assertFalse(x["trading_authorized"])
    def test_no_named_agents_is_not_approval(self):
        x=review_public_agents(fetcher=lambda kind,user:[],clock=lambda:0)
        self.assertEqual(x["agents"],[])
        self.assertFalse(x["trading_authorized"])
    def test_duplicate_invalid_role_and_malformed_hold(self):
        for rows in (None,{},[{"address":A,"validUntil":2000000000000}]*2,
                     [{"address":EXPECTED_ACCOUNT,"validUntil":2000000000000}]):
            with self.subTest(rows=rows),self.assertRaises(AgentHold):
                review_public_agents(fetcher=lambda kind,user:rows,clock=lambda:0)
    def test_mainnet_queries_not_possible(self):
        with self.assertRaises(AgentHold):
            read_public_agents("extraAgents","0x"+"0"*40)
        with self.assertRaises(AgentHold):
            read_public_agents("exchange",EXPECTED_ACCOUNT)
