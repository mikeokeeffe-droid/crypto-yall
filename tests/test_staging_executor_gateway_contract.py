import unittest
from staging_executor_gateway_contract import authorize_entry

class GatewayContractTests(unittest.TestCase):
    def test_every_bot_entry_denied(self):
        for bot in ('aggressive', 'intraday', 'daily'):
            for action in ('open_long', 'open_short', 'pyramid_long', 'pyramid_short'):
                with self.subTest(bot=bot, action=action):
                    result = authorize_entry(bot=bot, coin='BTC', action=action)
                    self.assertFalse(result.allowed)

    def test_invalid_and_close_requests_not_authorized(self):
        for bot, coin, action in [('invalid', 'BTC', 'open_long'), ('daily', '', 'open_long'), ('intraday', 'BTC', 'close')]:
            self.assertFalse(authorize_entry(bot=bot, coin=coin, action=action).allowed)

if __name__ == '__main__':
    unittest.main()
