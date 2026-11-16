"""Fail-closed runner OIDC transport and offline URL checks."""
import unittest

from sender_review import github_runner_oidc_handoff_review as r


class GithubRunnerOidcHandoffTests(unittest.TestCase):
    URL = "https://pipelines.actions.githubusercontent.com/abc/_apis/pipelines/workflows/xyz/idtoken"
    RUNNER = "example-runner-token-" + "q" * 30

    def test_runner_network_retrieval_never_enabled(self):
        for enabled in (True, False, None, 1, "yes"):
            for url in (self.URL, None, "https://example.invalid"):
                result = r.request_runner_oidc_token_review(
                    explicitly_enabled=enabled,
                    actions_request_url=url,
                    actions_request_token=self.RUNNER,
                )
                with self.subTest(enabled=enabled, url=url):
                    self.assertEqual(result.state, "hold")
                    self.assertIsNone(result.bearer_token)
                    self.assertFalse(result.candidate_token_present)
                    for field in (
                        "server_identity_authenticated", "sender_request_authorized",
                        "database_claim_recorded", "exchange_position_verified",
                        "submit_authorized", "close_authorized", "signing_enabled",
                    ):
                        self.assertFalse(getattr(result, field), field)
        self.assertFalse(hasattr(r, "urllib"))

    def test_offline_url_pinning_is_not_network_permission(self):
        result = r._token_endpoint_url(self.URL)
        self.assertEqual(result, self.URL + "?audience=" +
                         "urn%3Acrypto-yall%3Aprotected-sender%3Atestnet%3Areview")
        self.assertIsNone(r._token_endpoint_url(self.URL + "?audience=foo"))
        for invalid in ("http://pipelines.actions.githubusercontent.com/a/_apis/b/idtoken",
                        "https://example.invalid/abc/_apis/x/idtoken",
                        "https://pipelines.actions.githubusercontent.com.evil.invalid/abc/_apis/x/idtoken",
                        None):
            with self.subTest(url=invalid):
                self.assertIsNone(r._token_endpoint_url(invalid))


if __name__ == "__main__":
    unittest.main()
