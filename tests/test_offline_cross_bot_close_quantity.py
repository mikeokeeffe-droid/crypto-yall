"""Synthetic shared-account close quantity regression tests."""
import unittest
from offline_cross_bot_close_quantity import review_close_quantity_offline

BASE = dict(bot="daily", account="0xSynthetic", coin="SOL", side="long",
            close_size="1", exchange_size="3", provenance_verified=True)
def fill(id, bot, size, kind="entry"):
    return dict(id=id, bot=bot, account="0xSynthetic", coin="SOL",
                side="long", kind=kind, size=size)

class CloseQuantityTests(unittest.TestCase):
    def review(self, fills, **changes):
        return review_close_quantity_offline(fills=fills, **dict(BASE, **changes))

    def test_foreign_bot_quantity_cannot_be_closed(self):
        r = self.review([fill("a", "intraday", "3")])
        self.assertEqual(r.status, "hold")
        self.assertFalse(r.submit_authorized)

    def test_partial_own_quantity_only_review(self):
        r = self.review([fill("a", "daily", "1"), fill("b", "intraday", "2")])
        self.assertEqual(r.status, "review_only")
        self.assertFalse(r.submit_authorized)

    def test_own_prior_close_reduces_available_quantity(self):
        r = self.review([fill("a", "daily", "2"), fill("b", "daily", "1.5", "close")])
        self.assertEqual(r.status, "hold")

    def test_duplicate_or_wrong_account_holds(self):
        a = fill("a", "daily", "1")
        self.assertEqual(self.review([a, a]).status, "hold")
        self.assertEqual(self.review([dict(a, account="0xForeign")]).status, "hold")

    def test_unverified_provenance_holds(self):
        self.assertEqual(self.review([fill("a", "daily", "1")],
                                     provenance_verified=False).status, "hold")

    def test_unsized_and_oversized_holds(self):
        f = [fill("a", "daily", "1")]
        for size in ("0", "2", "", "NaN"):
            with self.subTest(size=size):
                self.assertEqual(self.review(f, close_size=size).status, "hold")

    def test_opposite_direction_netting_holds(self):
        opposite = dict(fill("b", "intraday", "1"), side="short")
        self.assertEqual(
            self.review([fill("a", "daily", "2"), opposite]).status, "hold"
        )

    def test_attributed_size_exceeding_exchange_holds(self):
        self.assertEqual(
            self.review([fill("a", "daily", "3")], exchange_size="2").status,
            "hold",
        )

    def test_partial_fill_without_complete_evidence_holds(self):
        self.assertEqual(
            self.review([fill("a", "daily", "0.4")], close_size="1").status,
            "hold",
        )

if __name__ == "__main__":
    unittest.main()
