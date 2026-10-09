"""Integration tests for local browser service, without real API requests."""
import json
import threading
import unittest
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
from unittest.mock import patch

from amap_lookup import rank_candidates, summarize
from web_app import make_server


class WebTests(unittest.TestCase):
    def setUp(self):
        self.server = make_server()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, data=None, headers=None):
        request_headers = {"X-App-Token": self.server.token, "Content-Type": "application/json"}
        request_headers.update(headers or {})
        req = Request(self.url + path, json.dumps(data).encode() if data is not None else None, request_headers)
        return build_opener(ProxyHandler({})).open(req, timeout=3)

    def test_page_renders_without_echoing_saved_keys(self):
        with patch("web_app.load_config", return_value={"key": "synthetic-private-amap"}), patch("web_app.load_settings", return_value={"key": "synthetic-private-ai"}):
            with self.request("/?demo") as response:
                html = response.read().decode()
            with self.request("/api/settings") as response:
                settings = response.read().decode()
        self.assertIn("地点查询工作台", html)
        self.assertIn(self.server.token, html)
        self.assertNotIn("__APP_TOKEN__", html)
        self.assertNotIn("synthetic-private", html + settings)
        self.assertTrue(json.loads(settings)["has_key"])

    def test_api_requires_session_token(self):
        with self.assertRaises(HTTPError) as error:
            self.request("/api/settings", headers={"X-App-Token": "wrong-token"})
        self.assertEqual(error.exception.code, 403)

    def test_cross_origin_and_rebound_host_are_rejected(self):
        for headers in ({"Origin": "https://external.invalid"}, {"Host": "external.invalid"}):
            with self.assertRaises(HTTPError) as error:
                self.request("/api/query", {"names": ["示例园"]}, headers=headers)
            self.assertEqual(error.exception.code, 403)

    def test_batch_uses_saved_key_and_returns_complete_result_events(self):
        candidate = {"name": "示例园", "address": "示例路1号", "adname": "示例区"}
        result = summarize("示例园", rank_candidates([candidate], "示例园", "示例市"))
        with patch("web_app.load_config", return_value={"key": "synthetic-key"}), patch("web_app.load_settings", return_value={}), patch("web_app.save_config") as save, patch("web_app.save_settings"), patch("web_app.AmapClient.lookup", return_value=result):
            with self.request("/api/query", {"names": ["示例园", "示例园"], "city": "示例市"}) as response:
                job = json.load(response)
            self.assertEqual(job["total"], 1)
            for _ in range(20):
                if not self.server.service.running:
                    break
                threading.Event().wait(.01)
            with self.request("/api/poll", {"job": job["job"], "cursor": 0}) as response:
                snapshot = json.load(response)
            self.assertEqual([e[0] for e in snapshot["events"]], ["result", "done"])
            self.assertEqual(snapshot["events"][0][1]["selected"]["address"], "示例区示例路1号")
            self.assertNotIn("synthetic-key", json.dumps(snapshot))
            save.assert_called_once_with("synthetic-key", "示例市", False)

    def test_invalid_input_and_stale_stop_do_not_run_queries(self):
        for data in ({"names": []}, {"names": ["a"] * 501 + [str(i) for i in range(501)]}, {"names": "bad"}):
            with self.assertRaises(HTTPError) as error:
                self.request("/api/query", data)
            self.assertEqual(error.exception.code, 400)
        with self.assertRaises(HTTPError) as error:
            self.request("/api/stop", {"job": "stale"})
        self.assertEqual(error.exception.code, 400)
        self.assertFalse(self.server.service.stop.is_set())

    def test_saved_key_removal_keeps_current_session_usable(self):
        service = self.server.service
        with patch("web_app.load_config", return_value={}), patch("web_app.load_settings", return_value={}), patch.dict("os.environ", {"AMAP_KEY": "", "DEEPSEEK_API_KEY": ""}), patch("web_app.save_config"), patch("web_app.save_settings"), patch.object(service, "_work"):
            service.start({"names": ["示例园"], "key": "synthetic-session-key"})
            service.running = False
            service.start({"names": ["示例园二"], "key": ""})
            self.assertEqual(service.client.key, "synthetic-session-key")

    def test_switching_endpoint_does_not_reuse_saved_key_from_another_provider(self):
        settings = {"key": "synthetic-private-ai", "endpoint": "https://api.deepseek.com/chat/completions"}
        with patch("web_app.load_config", return_value={"key": "synthetic-map"}), patch("web_app.load_settings", return_value=settings), patch.dict("os.environ", {"AI_API_KEY": "", "DEEPSEEK_API_KEY": "", "AI_ENDPOINT": ""}), patch("web_app.save_config") as save:
            with self.assertRaisesRegex(ValueError, "独立 API Key"):
                self.server.service.start({"names": ["示例园"], "ai_enabled": True,
                                           "endpoint": "https://api.example.com/v1/chat/completions", "model": "example-model"})
            save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
