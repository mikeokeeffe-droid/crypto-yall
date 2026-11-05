"""No live exchange; deterministic in-memory concurrency checks."""
import concurrent.futures
import unittest
from offline_shared_sender_prototype import OfflineSharedSender, FakeExchange

ACCOUNT = "0x" + "1" * 40
def args(account=ACCOUNT):
    return dict(environment="mainnet", account=account, dex="", coin="SOL")

class OfflineSharedSenderTests(unittest.TestCase):
    def test_three_bots_compete_one_scope(self):
        sender = OfflineSharedSender()
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(
                lambda bot: sender.reserve(bot=bot, side="long", size="2", **args()),
                ("daily", "intraday", "aggressive")))
        winners = [r for r in results if r.state == "reserved"]
        self.assertEqual(len(winners), 1)
        self.assertEqual(len({r.cloid for r in winners}), 1)
        self.assertTrue(all(not r.submit_authorized for r in results))

    def test_fake_dispatch_once_even_after_repeat(self):
        sender, fake = OfflineSharedSender(), FakeExchange()
        claim = sender.reserve(bot="daily", side="long", size="2", **args())
        kw = dict(token=claim.token, fence=claim.fence, fake=fake, **args())
        self.assertEqual(sender.simulate_once(**kw).state, "observed_unverified")
        self.assertEqual(sender.simulate_once(**kw).state, "hold")
        self.assertEqual(len(fake.attempts), 1)

    def test_failed_fake_send_remains_locked(self):
        class FailingFake(FakeExchange):
            def record_fake_attempt(self, token, cloid):
                raise TimeoutError("synthetic lost reply")
        sender = OfflineSharedSender()
        claim = sender.reserve(bot="daily", side="long", size="2", **args())
        kw = dict(token=claim.token, fence=claim.fence, fake=FailingFake(), **args())
        self.assertEqual(sender.simulate_once(**kw).state, "hold")
        self.assertEqual(sender.simulate_once(**kw).state, "hold")
        self.assertEqual(sender.reserve(bot="intraday", side="short", size="1", **args()).state, "hold")

    def test_wrong_token_fence_and_exchange_rejected(self):
        sender = OfflineSharedSender()
        claim = sender.reserve(bot="daily", side="long", size="2", **args())
        fake = FakeExchange()
        for token, fence in (("wrong",claim.fence),(claim.token,claim.fence+1),
                             (claim.token,True)):
            self.assertEqual(sender.simulate_once(token=token, fence=fence,
                                                  fake=fake, **args()).state, "hold")
        self.assertEqual(sender.simulate_once(token=claim.token, fence=claim.fence,
                                              fake=object(), **args()).state, "hold")
        self.assertEqual(fake.attempts, [])

    def test_separate_accounts_have_separate_reservations(self):
        sender = OfflineSharedSender()
        a = sender.reserve(bot="daily", side="long", size="1", **args())
        b = sender.reserve(bot="intraday", side="short", size="1",
                           **args("0x" + "2" * 40))
        self.assertEqual((a.state,b.state), ("reserved","reserved"))
        self.assertNotEqual(a.cloid,b.cloid)

    def test_no_live_exchange_interface(self):
        import offline_shared_sender_prototype as module
        self.assertFalse(hasattr(module, "Exchange"))
        self.assertFalse(hasattr(module, "market_open"))
        self.assertFalse(hasattr(module, "market_close"))

if __name__ == "__main__":
    unittest.main()
