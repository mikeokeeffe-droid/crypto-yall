import unittest
from unittest.mock import patch
from types import SimpleNamespace
from trusted_reconciler_release_staging import release_verified

class ReleaseTests(unittest.TestCase):
    def run_release(self, checks, rpc):
        with patch('trusted_reconciler_release_staging.reconcile_closed',
                   side_effect=[SimpleNamespace(action=x) for x in checks]) as verify:
            result = release_verified(None, 'address', rpc, coin='SOL',
                                      bot='intraday', token='token', clock=lambda: 1)
        return result, verify.call_count

    def test_two_fresh_checks_before_release(self):
        calls = []
        result, count = self.run_release(['release_candidate', 'release_candidate'],
                                         lambda fn, args: calls.append(fn) or True)
        self.assertTrue(result)
        self.assertEqual(count, 2)
        self.assertEqual(calls, ['mark_bot_position_closed', 'release_closed_bot_position'])

    def test_other_bots_cannot_release_at_boundary(self):
        for bot in ('aggressive', 'daily'):
            with self.subTest(bot=bot):
                calls = []
                with patch('trusted_reconciler_release_staging.reconcile_closed') as verify:
                    result = release_verified(None, 'address',
                        lambda fn, args: calls.append(fn) or True,
                        coin='SOL', bot=bot, token='token', clock=lambda: 1)
                self.assertFalse(result)
                verify.assert_not_called()
                self.assertEqual(calls, [])

    def test_first_check_holds(self):
        calls = []
        result, count = self.run_release(['hold'], lambda fn, args: calls.append(fn) or True)
        self.assertFalse(result)
        self.assertEqual(count, 1)
        self.assertEqual(calls, [])

    def test_second_check_holds(self):
        calls = []
        result, count = self.run_release(['release_candidate', 'hold'],
                                         lambda fn, args: calls.append(fn) or True)
        self.assertFalse(result)
        self.assertEqual(count, 2)
        self.assertEqual(calls, ['mark_bot_position_closed'])

    def test_failed_mark_prevents_release(self):
        calls = []
        result, count = self.run_release(['release_candidate'],
                                         lambda fn, args: calls.append(fn) or False)
        self.assertFalse(result)
        self.assertEqual(count, 1)

    def test_release_rpc_failure_holds(self):
        def rpc(fn, args):
            if fn == 'release_closed_bot_position':
                raise ConnectionError('offline')
            return True
        result, count = self.run_release(['release_candidate', 'release_candidate'], rpc)
        self.assertFalse(result)
        self.assertEqual(count, 2)

if __name__ == '__main__':
    unittest.main()
