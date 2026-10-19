"""Safe, offline tests: no exchange credentials, accounts or orders."""
import unittest
from usd_loss_cap import loss_cap_breached


class TestLossCap(unittest.TestCase):
    def test_crossing_threshold(self):
        self.assertFalse(loss_cap_breached(-0.199, 0.20))
        self.assertTrue(loss_cap_breached(-0.20, 0.20))
        self.assertTrue(loss_cap_breached(-0.59, 0.20))

    def test_positive_and_zero_pnl(self):
        self.assertFalse(loss_cap_breached(0.0, 0.20))
        self.assertFalse(loss_cap_breached(0.30, 0.20))

    def test_cap_disabled(self):
        self.assertFalse(loss_cap_breached(-9.0, 0.0))
        self.assertFalse(loss_cap_breached(-9.0, -0.20))

    def test_invalid_values_cannot_close(self):
        for value in (None, '', 'not-a-number', float('nan'), float('inf')):
            self.assertFalse(loss_cap_breached(value, 0.20))
        for cap in (None, '', float('nan'), float('inf')):
            self.assertFalse(loss_cap_breached(-0.30, cap))


if __name__ == '__main__':
    unittest.main()
