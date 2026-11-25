import unittest
from testnet_paper_review.testnet_spot_funds_probe import review_usdc_spot,SpotHold
class SpotTests(unittest.TestCase):
 def test_funds(self):
  x=review_usdc_spot({'balances':[{'coin':'USDC','total':'1000.0','hold':'0.0'}]})
  self.assertEqual(x['available'],'1000.0')
  self.assertFalse(x['may_trade'])
 def test_bad_data(self):
  for x in ({'balances':None},{'balances':[{'coin':'USDC','total':'0','hold':'1'}]}):
   with self.assertRaises(SpotHold):review_usdc_spot(x)
