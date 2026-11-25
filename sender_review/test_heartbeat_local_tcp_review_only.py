"""Real loopback TCP heartbeat round-trip in CI, without a deployed listener.

This is a SYNTHETIC TWO-PEER transport smoke test. It opens a localhost-only
ephemeral HTTP server within this test process. No bot, exchange, GitHub
secret, host network deployment, TLS certificate or trading channel is used.
The real remote-host topology and TLS/identity must be confirmed separately.
"""
import contextlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest

from sender_review.heartbeat_link_review_only import (
    HeartbeatObserver,
    HeartbeatReceiver,
    HeartbeatRejected,
    create_probe,
)

_KEY = b"CI-ONLY-NEVER-DEPLOY-heartbeat-test-key-" * 2
_BOOT = "1" * 32
_NONCE = "2" * 32


def _handler_for(receiver, *, clock_seconds=1700000000):
    class HeartbeatOnlyFixtureHandler(BaseHTTPRequestHandler):
        # The fixture handler cannot accept any order/intents route or method.
        protocol_version = "HTTP/1.0"

        def log_message(self, *_args):
            # Never print the request; it might contain credentials in an
            # altered test scenario. This is only a local disposable fixture.
            pass

        def do_GET(self):
            self.send_error(405, "method not allowed")

        def do_POST(self):
            if self.path != "/v1/review-only/heartbeat":
                self.send_error(404, "route not found")
                return
            lengths = self.headers.get_all("Content-Length", [])
            if (len(lengths) != 1 or not lengths[0].isdigit()
                    or not 1 <= int(lengths[0]) <= 512
                    or self.headers.get("Transfer-Encoding") is not None
                    or self.headers.get("Content-Type") != "application/json"):
                self.send_error(400, "malformed frame")
                return
            try:
                body = self.rfile.read(int(lengths[0]))
                response = receiver.receive(probe=body, now=clock_seconds)
            except HeartbeatRejected:
                self.send_error(403, "heartbeat denied")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

    return HeartbeatOnlyFixtureHandler


@contextlib.contextmanager
def _loopback_server(receiver):
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), _handler_for(receiver)
    )
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        if thread.is_alive():
            raise AssertionError("fixture TCP server failed to shut down")


def _post(port, raw, *, path="/v1/review-only/heartbeat"):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request(
            "POST", path, body=raw,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def _probe(*, seq=1, nonce=_NONCE, key=_KEY):
    return create_probe(
        key=key, boot=_BOOT, seq=seq, nonce=nonce, now=1700000000
    )


class HeartbeatLocalTcpReviewTests(unittest.TestCase):
    def test_actual_loopback_tcp_roundtrip_signed_ack_and_timeout(self):
        receiver = HeartbeatReceiver(key=_KEY)
        observer = HeartbeatObserver(
            key=_KEY, timeout_seconds=6.0, max_rtt_seconds=2.0,
        )
        request = _probe()
        with _loopback_server(receiver) as port:
            status, ack = _post(port, request)
            self.assertEqual(status, 200)
            result = observer.acknowledge(
                probe=request, ack=ack, now=1700000000,
                sent_monotonic=8.00, recv_monotonic=8.04,
            )
            self.assertTrue(result.connected)
            self.assertEqual(result.last_rtt_ms, 40)
            self.assertTrue(observer.status(now_monotonic=13.9).connected)
            # A valid response at the wrong route cannot be mistaken for ACK.
            bad_route, _ = _post(port, _probe(seq=2), path="/v1/orders")
            self.assertEqual(bad_route, 404)
        self.assertFalse(observer.status(now_monotonic=14.1).connected)
        self.assertEqual(observer.status(now_monotonic=14.1).reason,
                         "heartbeat timeout")

    def test_network_replay_tamper_and_order_field_rejected(self):
        receiver = HeartbeatReceiver(key=_KEY)
        valid = _probe()
        with _loopback_server(receiver) as port:
            self.assertEqual(_post(port, valid)[0], 200)
            self.assertEqual(_post(port, valid)[0], 403)
            self.assertEqual(_post(port, _probe(seq=2, key=b"WRONG" * 10))[0], 403)
            malicious = json.loads(_probe(seq=2))
            malicious["action"] = "market_close"
            self.assertEqual(_post(port, json.dumps(malicious).encode())[0], 403)
            self.assertEqual(_post(port, b'{"foo": "bar"}')[0], 403)
            self.assertEqual(_post(port, b"x" * 513)[0], 400)
            self.assertEqual(_post(port, _probe(seq=3), path="/execute")[0], 404)

    def test_connection_failure_does_not_infer_any_trading_authority(self):
        observer = HeartbeatObserver(key=_KEY)
        with _loopback_server(HeartbeatReceiver(key=_KEY)) as port:
            status, ack = _post(port, _probe())
            self.assertEqual(status, 200)
            self.assertIn(b"heartbeat_ack", ack)
        self.assertFalse(observer.status(now_monotonic=12).connected)
        self.assertFalse(hasattr(observer, "submit_order"))


if __name__ == "__main__":
    unittest.main()
