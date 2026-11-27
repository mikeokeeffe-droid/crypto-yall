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

 def test_fixed_testnet_mode_query_and_no_key(self):
  from testnet_paper_review.testnet_spot_funds_probe import read_account_mode
  class Response:
   status=200
   def read(self,n):return b'"unifiedAccount"'
  class Connection:
   def __init__(self):self.calls=[]
   def request(self,*args,**kwargs):self.calls.append((args,kwargs))
   def getresponse(self):return Response()
   def close(self):pass
  conn=Connection()
  self.assertEqual(read_account_mode(connection_factory=lambda:conn),"unifiedAccount")
  args,kwargs=conn.calls[0]
  self.assertEqual(args[:2],("POST","/info"))
  import json
  self.assertEqual(json.loads(kwargs["body"]),{"type":"userAbstraction","user":"0xF14348Bdf59BA186F9CdD0fC5F369e1f6D3b7dC0"})
 def test_unknown_mode_holds(self):
  from testnet_paper_review.testnet_spot_funds_probe import read_account_mode
  class Response:
   status=200
   def read(self,n):return b'"not-an-account-mode"'
  class Connection:
   def request(self,*args,**kwargs):pass
   def getresponse(self):return Response()
   def close(self):pass
  with self.assertRaises(SpotHold):
   read_account_mode(connection_factory=lambda:Connection())
