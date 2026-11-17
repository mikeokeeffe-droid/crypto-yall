"""No-I/O lock tests: unknown outcomes cannot be converted into re-entry."""
import ast
from pathlib import Path
import unittest

from sender_review.reentry_lock_transition_review_offline import (
    SyntheticReentryLock, inspect_reentry_lock_transition_offline,
)

NOW = 1700000000
def lock(bot="intraday", coin="SOL", side="long", nonce="a"*32, fence=4,
         state="unknown_ack", created_epoch=NOW-901):
    return SyntheticReentryLock(bot, coin, side, nonce, fence, state, created_epoch)

def action(coin="SOL", verb="open_long"):
    return {"hl_coin":coin,"action":verb,"side":"long"}

def review(**changes):
    args=dict(requesting_bot="daily", locks=(lock(),),
              proposals=(action(),action("AVAX"),action("SOL","close")),
              signal_by_coin={"SOL":"sell_exit"},
              synthetic_now_epoch=NOW)
    args.update(changes)
    return inspect_reentry_lock_transition_offline(**args)

class ReentryLockTransitionTests(unittest.TestCase):
    def assert_no_authority(self, result):
        self.assertEqual(result.state, "HOLD")
        for flag in ("account_wide_identity_verified","exchange_exit_confirmed",
                     "durable_lock_persisted","lock_released","retry_authorized",
                     "close_authorized","submit_authorized","signing_enabled"):
            self.assertIs(getattr(result,flag),False,flag)

    def test_unknown_ack_blocks_other_bot_and_exit_mutations_even_on_reset(self):
        r=review()
        self.assertTrue(r.fixture_valid)
        self.assertEqual(r.held_coins,("SOL",))
        self.assertEqual([x["action"] for x in r.blocked_actions],["open_long","close"])
        self.assertEqual([x["hl_coin"] for x in r.unaffected_review_proposals],["AVAX"])
        self.assertEqual(r.candidate_release_reviews,())
        self.assertTrue(r.operator_reconciliation_required)
        self.assert_no_authority(r)

    def test_no_cooldown_or_signal_reset_releases_unresolved(self):
        for bot in ("daily","intraday","aggressive"):
            for state in ("pending_exit","unknown_ack","partial_fill"):
                for signal in ("sell_exit","buy","cover_short"):
                    with self.subTest(bot=bot,state=state,signal=signal):
                        r=review(locks=(lock(bot=bot,state=state,created_epoch=NOW-86400),),
                                 signal_by_coin={"SOL":signal})
                        self.assertTrue(r.fixture_valid)
                        self.assertEqual(r.candidate_release_reviews,())
                        self.assertEqual(len(r.blocked_actions),2)
                        self.assert_no_authority(r)

    def test_confirmed_closed_claim_yields_review_candidate_not_unblock(self):
        for bot in ("intraday","aggressive"):
            for signal,expected in (("hold_long",()),("sell_exit",(("SOL","signal_reset_review"),))):
                with self.subTest(bot=bot,signal=signal):
                    r=review(locks=(lock(bot=bot,state="confirmed_closed_fixture"),),
                             signal_by_coin={"SOL":signal})
                    if bot=="aggressive" and signal=="hold_long":
                        expected=(("SOL","cooldown_review"),)
                    self.assertEqual(r.candidate_release_reviews,expected)
                    self.assertEqual(len(r.blocked_actions),2)
                    self.assertFalse(r.lock_released)
                    self.assert_no_authority(r)

    def test_duplicate_fence_scope_and_malformed_lock_fail_closed(self):
        for fixture in (
            (lock(),lock()),
            (lock(nonce="wrong"),),
            (lock(fence=True),),
            (lock(fence=0),),
            (lock(state="released"),),
            (lock(created_epoch=NOW+1),),
            (lock(bot="unknown"),),
            (lock(coin="BNB/../"),),
        ):
            with self.subTest(fixture=fixture):
                r=review(locks=fixture)
                self.assertFalse(r.fixture_valid)
                self.assertEqual(r.blocked_actions,())
                self.assert_no_authority(r)

    def test_wrong_inputs_and_unknown_actions_cannot_grant_access(self):
        cases=(
            {"requesting_bot":"unknown"},
            {"synthetic_now_epoch":True},
            {"proposals":({"hl_coin":"SOL","action":"market_open"},)},
            {"signal_by_coin":{"SOL":"execute"}},
            {"aggressive_cooldown_seconds":30},
            {"locks":list((lock(),))},
        )
        for change in cases:
            with self.subTest(change=str(change)):
                r=review(**change)
                self.assertFalse(r.fixture_valid)
                self.assert_no_authority(r)

    def test_empty_lock_sample_stays_hold_with_untrusted_proposal(self):
        r=review(locks=(), proposals=(action("SOL"),))
        self.assertTrue(r.fixture_valid)
        self.assertEqual(len(r.unaffected_review_proposals),1)
        self.assertFalse(r.submit_authorized)
        self.assert_no_authority(r)

    def test_source_has_no_runtime_sdk_db_http_or_clock_dependencies(self):
        src=Path(__file__).with_name("reentry_lock_transition_review_offline.py").read_text()
        names=set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node,ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node,ast.ImportFrom):
                names.add(node.module)
        self.assertEqual(names,{"dataclasses","re","sender_review.pure_strategy_decisions_offline"})

if __name__=="__main__":
    unittest.main()
