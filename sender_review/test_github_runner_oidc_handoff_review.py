"""Mock-only runner OIDC handoff tests; no network, DB or trading."""
import io
import unittest
from unittest.mock import patch

from sender_review import github_runner_oidc_handoff_review as handoff


class Response:
    def __init__(self, url, content, status=200, content_type="application/json"):
        self._url = url
        self._data = io.BytesIO(content)
        self.status = status
        self.headers = {"Content-Type": content_type}

    def geturl(self):
        return self._url

    def read(self, count):
        return self._data.read(count)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


class FakeOpener:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request.full_url, request.get_method(), timeout))
        return self.response


class GithubRunnerOidcHandoffTests(unittest.TestCase):
    URL = "https://pipelines.actions.githubusercontent.com/abc/_apis/pipelines/workflows/xyz/idtoken"
    RUNNER = "example-runner-token-" + "q" * 30
    JWT = "a" * 40 + "." + "b" * 80 + "." + "c" * 80

    def no_auth(self, result):
        for name in ("server_identity_authenticated", "sender_request_authorized",
                     "database_claim_recorded", "exchange_position_verified",
                     "submit_authorized", "close_authorized", "signing_enabled"):
            self.assertFalse(getattr(result, name), name)

    def test_default_denies_without_touching_network(self):
        with patch.object(handoff.urllib.request, "build_opener",
                          side_effect=AssertionError("no networking")):
            for enabled in (False, None, "yes", 1):
                with self.subTest(enabled=enabled):
                    r = handoff.request_runner_oidc_token_review(
                        explicitly_enabled=enabled,
                        actions_request_url=self.URL,
                        actions_request_token=self.RUNNER)
                    self.assertEqual(r.state, "hold")
                    self.assertIsNone(r.bearer_token)
                    self.no_auth(r)

    def test_mock_opt_in_token_never_authorizes_sender(self):
        url = handoff._token_endpoint_url(self.URL)
        self.assertIsNotNone(url)
        fake = FakeOpener(Response(url, ('{"value":"' + self.JWT + '"}').encode()))
        with patch.object(handoff.urllib.request, "build_opener",
                          return_value=fake):
            r = handoff.request_runner_oidc_token_review(
                explicitly_enabled=True,
                actions_request_url=self.URL,
                actions_request_token=self.RUNNER)
        self.assertEqual(r.state, "candidate_runner_token_unverified_HOLD")
        self.assertEqual(r.bearer_token, self.JWT)
        self.assertTrue(r.candidate_token_present)
        self.assertNotIn(self.JWT, repr(r))
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0][1], "GET")
        self.no_auth(r)

    def test_wrong_host_proxy_url_and_caller_audience_refused(self):
        for url in (
            "http://pipelines.actions.githubusercontent.com/x/_apis/idtoken",
            "https://evil.invalid/x/_apis/idtoken",
            "https://pipelines.actions.githubusercontent.com.evil.invalid/x/_apis/idtoken",
            "https://pipelines.actions.githubusercontent.com@evil.invalid/x/_apis/idtoken",
            self.URL + "?audience=evil",
            self.URL + "#fragment",
            self.URL.replace("/idtoken", "/orders"),
        ):
            with self.subTest(url=url):
                self.assertIsNone(handoff._token_endpoint_url(url))
        for token in (None, "short", self.RUNNER + "\n", self.RUNNER + "\0"):
            with self.subTest(token=token), patch.object(
                handoff.urllib.request, "build_opener",
                side_effect=AssertionError("network forbidden")
            ):
                r = handoff.request_runner_oidc_token_review(
                    explicitly_enabled=True, actions_request_url=self.URL,
                    actions_request_token=token)
                self.assertEqual(r.state, "hold")
                self.no_auth(r)

    def test_bad_response_metadata_and_bad_token_hold(self):
        url = handoff._token_endpoint_url(self.URL)
        for case in ("wrong_url", "rate_limit", "html", "oversize",
                     "broken_jwt", "duplicate_fields"):
            payload = ('{"value":"' + self.JWT + '"}').encode()
            resp = Response(url, payload)
            if case == "wrong_url":
                resp._url = "https://evil.invalid"
            if case == "rate_limit":
                resp.status = 429
            if case == "html":
                resp.headers["Content-Type"] = "text/html"
            if case == "oversize":
                resp._data = io.BytesIO(b"z" * 17000)
            if case == "broken_jwt":
                resp._data = io.BytesIO(b'{"value":"invalid"}')
            if case == "duplicate_fields":
                resp._data = io.BytesIO(
                    ('{"value":"' + self.JWT + '","value":"' + self.JWT + '"}').encode())
            with self.subTest(case=case), patch.object(
                handoff.urllib.request, "build_opener",
                return_value=FakeOpener(resp)
            ):
                r = handoff.request_runner_oidc_token_review(
                    explicitly_enabled=True, actions_request_url=self.URL,
                    actions_request_token=self.RUNNER)
                self.assertEqual(r.state, "hold")
                self.assertIsNone(r.bearer_token)
                self.no_auth(r)


if __name__ == "__main__":
    unittest.main()
