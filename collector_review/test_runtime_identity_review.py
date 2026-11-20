"""Offline collector runtime review tests; NEVER access real environment."""
import unittest

from collector_review.runtime_identity_review import inspect_runtime_identity_offline


def check(**kwargs):
    args=dict(effective_uid=2001, effective_gid=2001,
              expected_uid=2001, expected_gid=2001,
              environment_names=("PATH", "LANG", "HOME"),
              isolated_service_confirmed=True)
    args.update(kwargs)
    return inspect_runtime_identity_offline(**args)


class CollectorRuntimeIdentityTests(unittest.TestCase):
    def test_clean_caller_supplied_metadata_is_only_review_not_authority(self):
        r=check()
        self.assertEqual(r.state,"review_only")
        self.assertTrue(r.isolated_identity_candidate)
        self.assertTrue(r.credential_names_clear)
        self.assertFalse(r.network_egress_verified)
        self.assertFalse(r.origin_authenticated)
        self.assertFalse(r.trading_authorized)

    def test_root_or_mismatched_identity_holds(self):
        for k,v in (
            ("effective_uid",0), ("effective_gid",0),
            ("effective_uid",True),("effective_gid",False),
            ("effective_uid",2002),("effective_gid",2002),
            ("expected_uid",0),("expected_gid",0),
            ("expected_uid","2001"),
        ):
            with self.subTest(k=k,v=v):
                self.assertEqual(check(**{k:v}).state,"hold")

    def test_unreviewed_and_secret_env_names_hold_without_values(self):
        for name in (
            "HL_PRIVATE_KEY", "HL_API_KEY", "AWS_SECRET_ACCESS_KEY",
            "ACCOUNT_TOKEN", "SIGNING_KEY", "API_SECRET",
            "CUSTOM_SETTING", "HTTP_PROXY", "HTTPS_PROXY",
            "PYTHONPATH", "OPENAI_API_KEY",
        ):
            with self.subTest(name=name):
                r=check(environment_names=("HOME",name))
                self.assertEqual(r.state,"hold")
                self.assertFalse(r.trading_authorized)
        self.assertEqual(check(environment_names=("HOME","HOME")).state,"hold")
        self.assertEqual(check(environment_names=("HOME",None)).state,"hold")
        self.assertEqual(check(environment_names="HOME").state,"hold")

    def test_unconfirmed_isolation_always_holds(self):
        for flag in (False,None,"true",0):
            with self.subTest(flag=flag):
                r=check(isolated_service_confirmed=flag)
                self.assertEqual(r.state,"hold")
                self.assertFalse(r.network_egress_verified)


if __name__=="__main__":
    unittest.main()
