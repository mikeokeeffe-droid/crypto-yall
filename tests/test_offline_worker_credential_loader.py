"""Offline credential file failure tests, no production secrets."""
import json
import os
import tempfile
import unittest
from offline_worker_credential_loader import load_offline_worker_keys

class CredentialFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=os.path.join(self.temp.name,"fixture-credentials.json")
    def tearDown(self):
        self.temp.cleanup()
    def write(self,data,mode=0o600):
        with open(self.path,"wb") as stream:
            stream.write(data)
        os.chmod(self.path,mode)
    def test_valid_disposable_key(self):
        self.write(json.dumps({"daily-principal":(b"d"*32).hex()}).encode())
        self.assertEqual(load_offline_worker_keys(self.path),
                         {"daily-principal":b"d"*32})
    def test_missing_credentials_fail_closed(self):
        with self.assertRaises(RuntimeError):
            load_offline_worker_keys(self.path)
    def test_invalid_and_short_credentials_fail_closed(self):
        for data in (b"",b"not json",b"{}",b'{"daily-principal":"ff"}',
                     b'{"daily-principal":"zz"}',b"[]" ):
            self.write(data)
            with self.subTest(data=data),self.assertRaises(RuntimeError):
                load_offline_worker_keys(self.path)
    def test_world_readable_credentials_rejected(self):
        self.write(json.dumps({"daily-principal":(b"d"*32).hex()}).encode(),0o644)
        with self.assertRaises(RuntimeError):
            load_offline_worker_keys(self.path)
    def test_symlink_credentials_rejected(self):
        target=os.path.join(self.temp.name,"target")
        with open(target,"wb") as stream:
            stream.write(json.dumps({"daily-principal":(b"d"*32).hex()}).encode())
        os.chmod(target,0o600)
        os.symlink(target,self.path)
        with self.assertRaises(RuntimeError):
            load_offline_worker_keys(self.path)
    def test_unreadable_or_removed_credentials_rejected(self):
        self.write(json.dumps({"daily-principal":(b"d"*32).hex()}).encode())
        os.unlink(self.path)
        with self.assertRaises(RuntimeError):
            load_offline_worker_keys(self.path)

if __name__=="__main__":
    unittest.main()
