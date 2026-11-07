"""Offline tests for the staging-only HTTPS gateway transport."""
import ssl
import unittest
from email.message import Message
from unittest.mock import Mock, patch

import staging_executor_gateway_host as gateway
from staging_executor_gateway_contract import BOTS


ENDPOINT = "https://gateway.staging.internal:8443"
APPROVED_IP = "10.20.30.40"
ALLOWLIST = {ENDPOINT: {APPROVED_IP}}
SUCCESS_BODY = b'{"reservation_claimed":true,"intent_claimed":true}'


class FakeResponse:
    def __init__(self, status=200, body=SUCCESS_BODY, headers=None):
        self.status = status
        self.headers = Message()
        for key, value in (headers or {}).items():
            if isinstance(value, list):
                for item in value:
                    self.headers.add_header(key, item)
            else:
                self.headers.add_header(key, value)
        self.body = body
        self.read_sizes = []

    def read(self, size):
        self.read_sizes.append(size)
        return self.body[:size]


class FakeHTTPSConnection:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.sock = Mock()
        self.requests = []
        self.response = self.__class__.response
        self.closed = False
        self.__class__.instances.append(self)

    def request(self, *args, **kwargs):
        self.requests.append((args, kwargs))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class StagingExecutorHTTPSTransportTests(unittest.TestCase):
    def setUp(self):
        FakeHTTPSConnection.instances = []
        FakeHTTPSConnection.response = FakeResponse(
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Content-Length": str(len(SUCCESS_BODY)),
            },
        )
        self.transport = gateway.StagingExecutorHTTPSJSONTransport(
            endpoint_url=ENDPOINT,
            allowed_destinations=ALLOWLIST,
            connect_timeout_seconds=1.5,
            read_timeout_seconds=2.5,
        )
        self.resolved = [
            (2, 1, 6, "", (APPROVED_IP, 8443)),
        ]

    def call_transport(self, transport=None, *, timeout=3.0, headers=None):
        with (
            patch.object(gateway.socket, "getaddrinfo", return_value=self.resolved),
            patch.object(
                gateway,
                "_PinnedHTTPSConnection",
                FakeHTTPSConnection,
            ),
        ):
            return (transport or self.transport)(
                method="POST",
                path=gateway.ENTRY_CLAIM_PATH,
                headers=headers or {
                    "Authorization": "Bearer synthetic.jwt.token",
                    "Content-Type": "application/json",
                },
                body=b'{"bot":"aggressive","coin":"BTC","action":"open_long"}',
                timeout=timeout,
            )

    def test_tls_verifies_certificates_and_hostname(self):
        self.assertEqual(self.transport._tls_context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(self.transport._tls_context.check_hostname)

    def test_transport_uses_allowlisted_private_ip_and_separate_timeouts(self):
        status, body = self.call_transport()
        self.assertEqual((status, body), (200, SUCCESS_BODY))
        connection = FakeHTTPSConnection.instances[0]
        self.assertEqual(connection.kwargs["hostname"], "gateway.staging.internal")
        self.assertEqual(connection.kwargs["address"], APPROVED_IP)
        self.assertEqual(connection.kwargs["timeout"], 1.5)
        self.assertEqual(connection.sock.settimeout.call_args.args, (2.5,))
        args, kwargs = connection.requests[0]
        self.assertEqual(args, ("POST", gateway.ENTRY_CLAIM_PATH))
        self.assertEqual(kwargs["headers"]["Host"], "gateway.staging.internal:8443")
        self.assertEqual(
            kwargs["headers"]["Authorization"],
            "Bearer synthetic.jwt.token",
        )
        self.assertTrue(connection.closed)

    def test_client_uses_separate_per_bot_signing_identities(self):
        keys = {
            bot: f"synthetic-{bot}-signing-key-with-at-least-32-bytes".encode()
            for bot in BOTS
        }
        host = gateway.StagingExecutorGatewayHost(
            app=lambda environ, start_response: [],
            signing_keys=keys,
            issuer="synthetic-staging-issuer",
            audience="synthetic-staging-audience",
        )
        client = host.create_client(
            endpoint_url=ENDPOINT,
            allowed_destinations=ALLOWLIST,
        )
        authorizations = []

        class CaptureConnection(FakeHTTPSConnection):
            def request(self, *args, **kwargs):
                authorizations.append(kwargs["headers"]["Authorization"])
                super().request(*args, **kwargs)

        with (
            patch.object(gateway.socket, "getaddrinfo", return_value=self.resolved),
            patch.object(gateway, "_PinnedHTTPSConnection", CaptureConnection),
        ):
            for bot in BOTS:
                result = client(bot=bot, coin="BTC", action="open_long")
                self.assertEqual(result["reservation_claimed"], True)
        self.assertEqual(len(set(authorizations)), len(BOTS))

    def test_http_and_unallowlisted_or_public_destinations_are_rejected(self):
        with self.assertRaises(ValueError):
            gateway.StagingExecutorHTTPSJSONTransport(
                endpoint_url="http://gateway.staging.internal",
                allowed_destinations=ALLOWLIST,
            )
        with self.assertRaises(ValueError):
            gateway.StagingExecutorHTTPSJSONTransport(
                endpoint_url="https://unlisted.staging.internal",
                allowed_destinations=ALLOWLIST,
            )
        with self.assertRaises(ValueError):
            gateway.StagingExecutorHTTPSJSONTransport(
                endpoint_url=ENDPOINT,
                allowed_destinations={ENDPOINT: {"203.0.113.10"}},
            )

        public_dns = [(2, 1, 6, "", ("8.8.8.8", 8443))]
        self.resolved = public_dns
        with self.assertRaises(gateway.GatewayClientError):
            self.call_transport()
        self.assertEqual(FakeHTTPSConnection.instances, [])

    def test_redirect_is_rejected_without_following_location(self):
        FakeHTTPSConnection.response = FakeResponse(
            status=302,
            headers={"Location": "https://other.example/collect"},
        )
        with self.assertRaises(gateway.GatewayClientError):
            self.call_transport()
        self.assertEqual(len(FakeHTTPSConnection.instances), 1)

    def test_response_size_content_type_and_encoding_are_strict(self):
        FakeHTTPSConnection.response = FakeResponse(
            body=b"x" * (gateway.MAX_RESPONSE_BYTES + 1),
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(gateway.MAX_RESPONSE_BYTES + 1),
            },
        )
        with self.assertRaises(gateway.GatewayClientError):
            self.call_transport()

        for headers in (
            {"Content-Type": "text/plain", "Content-Length": "2"},
            {
                "Content-Type": "application/json",
                "Content-Encoding": "gzip",
                "Content-Length": "2",
            },
            {
                "Content-Type": "application/json",
                "Content-Length": ["1", "1"],
            },
            {
                "Content-Type": "application/json",
                "Content-Length": "2",
                "Transfer-Encoding": "chunked",
            },
            {
                "Content-Type": "application/json",
                "Transfer-Encoding": "gzip",
            },
        ):
            FakeHTTPSConnection.response = FakeResponse(body=b"{}", headers=headers)
            with self.subTest(headers=headers), self.assertRaises(
                gateway.GatewayClientError
            ):
                self.call_transport()

        FakeHTTPSConnection.response = FakeResponse(
            body=b"x" * (gateway.MAX_RESPONSE_BYTES + 1),
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(gateway.GatewayClientError):
            self.call_transport()
        self.assertEqual(
            FakeHTTPSConnection.instances[-1].response.read_sizes,
            [gateway.MAX_RESPONSE_BYTES + 1],
        )

    def test_malformed_and_duplicate_success_json_fail_closed(self):
        for body in (
            b'{"reservation_claimed":true,"reservation_claimed":true,'
            b'"intent_claimed":true}',
            b'{"reservation_claimed":true,"intent_claimed":false}',
            b"not-json",
        ):
            with self.subTest(body=body):
                client = gateway.StagingExecutorGatewayClient(
                    transport=lambda **request: (200, body),
                    token_provider=lambda bot: "synthetic-token",
                    timeout_seconds=1,
                )
                with self.assertRaises(gateway.GatewayClientError):
                    client(bot="daily", coin="BTC", action="open_long")

    def test_transport_factory_requires_endpoint_allowlist(self):
        host = gateway.StagingExecutorGatewayHost(
            app=lambda environ, start_response: [],
            signing_keys={bot: b"x" * 32 for bot in BOTS},
            issuer="synthetic-issuer",
            audience="synthetic-audience",
        )
        with self.assertRaises(ValueError):
            host.create_client()
        with self.assertRaises(ValueError):
            host.create_client(
                endpoint_url=ENDPOINT,
                allowed_destinations=ALLOWLIST,
                transport=lambda **request: (200, SUCCESS_BODY),
            )

    def test_certificate_verification_failure_is_not_bypassed(self):
        raw_socket = Mock()
        context = Mock()
        context.wrap_socket.side_effect = ssl.SSLCertVerificationError(
            "synthetic invalid certificate"
        )
        connection = gateway._PinnedHTTPSConnection(
            hostname="gateway.staging.internal",
            port=8443,
            address=APPROVED_IP,
            context=context,
            timeout=1,
        )
        with (
            patch.object(gateway.socket, "create_connection", return_value=raw_socket),
            self.assertRaises(ssl.SSLCertVerificationError),
        ):
            connection.connect()
        context.wrap_socket.assert_called_once_with(
            raw_socket,
            server_hostname="gateway.staging.internal",
        )
        raw_socket.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
