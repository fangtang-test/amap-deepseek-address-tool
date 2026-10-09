import io
import socket
import ssl
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from transport import LookupError, classify_error, request_json


class TransportTests(unittest.TestCase):
    @patch("transport.time.sleep")
    def test_temporary_failure_retries_then_succeeds(self, sleep):
        opener = Mock(side_effect=[URLError(socket.timeout()), io.BytesIO(b'{"status":"1"}')])
        progress = []
        data = request_json(Request("https://example.invalid"), opener, "高德", timeout=10, on_retry=progress.append)
        self.assertEqual(data["status"], "1")
        self.assertEqual(opener.call_count, 2)
        self.assertIn("超时", progress[0])
        self.assertIn("2/3", progress[0])

    @patch("transport.time.sleep")
    def test_retry_exhaustion_is_single_item_failure(self, sleep):
        opener = Mock(side_effect=URLError(ConnectionResetError(10054, "sensitive-url-with-key")))
        with self.assertRaises(LookupError) as error:
            request_json(Request("https://example.invalid"), opener, "高德", timeout=10)
        self.assertEqual(opener.call_count, 3)
        self.assertFalse(error.exception.stop_batch)
        self.assertIn("已尝试 3 次", str(error.exception))
        self.assertNotIn("sensitive", str(error.exception))

    def test_unauthorized_does_not_retry(self):
        opener = Mock(side_effect=HTTPError("secret-url", 401, "secret-key", {}, None))
        with self.assertRaises(LookupError) as error:
            request_json(Request("https://example.invalid"), opener, "DeepSeek", timeout=10)
        self.assertEqual(opener.call_count, 1)
        self.assertTrue(error.exception.stop_batch)
        self.assertNotIn("secret", str(error.exception))

    def test_dns_timeout_and_certificate_have_distinct_messages(self):
        dns = classify_error(URLError(socket.gaierror(-2, "secret")), "高德")
        timeout = classify_error(URLError(socket.timeout()), "高德")
        certificate = classify_error(URLError(ssl.SSLCertVerificationError("secret")), "高德")
        self.assertIn("DNS", str(dns))
        self.assertIn("超时", str(timeout))
        self.assertIn("证书", str(certificate))
        self.assertFalse(certificate.retryable)

    def test_stop_during_retry_backoff_prevents_next_request(self):
        cancel = threading.Event()
        opener = Mock(side_effect=URLError(socket.timeout()))
        with self.assertRaisesRegex(LookupError, "停止"):
            request_json(Request("https://example.invalid"), opener, "高德", timeout=10,
                         cancel_event=cancel, on_retry=lambda message: cancel.set())
        self.assertEqual(opener.call_count, 1)


if __name__ == "__main__":
    unittest.main()
