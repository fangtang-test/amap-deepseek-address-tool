import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError

import ai_filter as ai
from amap_lookup import ROOT, LookupError, export_csv, rank_candidates, summarize


def result():
    candidates = rank_candidates([
        {"id": "test-one", "name": "测试园", "address": "示例路1号", "adname": "番禺区"},
        {"id": "test-two", "name": "测试园分园", "address": "示例路2号", "adname": "番禺区"},
        {"id": "test-three", "name": "测试园餐饮店", "address": "示例路3号", "adname": "番禺区"},
    ], "测试园", "广州")
    return summarize("测试园", candidates)


def match(index, confidence, review=False):
    return {"candidate_index": index, "confidence": confidence, "needs_review": review, "reason": "仅用于离线测试的判断依据"}


class AiTests(unittest.TestCase):
    def test_multiple_high_confidence_addresses_preserved(self):
        r = ai.apply_decision(result(), {"matches": [match(0, 96), match(1, 92)], "reason": "两个相关园区主体"})
        self.assertEqual([p["address"] for p in r["selected_items"]], ["番禺区示例路1号", "番禺区示例路2号"])

    def test_uncertain_or_low_confidence_does_not_force_match(self):
        for score, review in ((75, False), (95, True), (59, False), (89.999, False)):
            r = ai.apply_decision(result(), {"matches": [match(0, score, review)], "reason": "证据不足"})
            self.assertEqual(r["selected_items"], [])
            self.assertIsNone(r["selected"])
            self.assertEqual(r["candidates"][0]["ai_confidence"], score)

    def test_no_match_clears_previous_name_only_match(self):
        r = result()
        self.assertIsNotNone(r["selected"])
        ai.apply_decision(r, {"matches": [], "reason": "无法确认主体身份"})
        self.assertEqual(r["selected_items"], [])
        self.assertIn("无法确认", r["status"])

    def test_invalid_index_or_score_rejects_entire_response(self):
        for invalid in (match(99, 95), match(-1, 95), match(True, 95), match(0, 101), match(0, float("nan")), match(0, True)):
            r = result()
            original = r["selected_items"][:]
            with self.assertRaises(LookupError):
                ai.apply_decision(r, {"matches": [match(1, 96), invalid], "reason": "测试无效结果"})
            self.assertEqual(r["selected_items"], original)
            self.assertNotIn("ai_confidence", r["candidates"][1])

    def test_ai_cannot_fabricate_or_replace_address(self):
        decision = {"matches": [{**match(1, 95), "address": "虚构路999号"}], "reason": "测试额外字段"}
        r = ai.apply_decision(result(), decision)
        self.assertEqual(r["selected_items"][0]["address"], "番禺区示例路2号")

    def test_csv_has_multiple_rows_and_keeps_uncertain_result_empty(self):
        first = ai.apply_decision(result(), {"matches": [match(0, 96), match(1, 92)], "reason": "测试多选"})
        second = ai.apply_decision(result(), {"matches": [match(0, 75, True)], "reason": "证据不足需核对"})
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            self.assertTrue(Path(folder).resolve().is_relative_to(ROOT.resolve()))
            target = Path(folder) / "test.csv"
            export_csv(target, [first, second])
            with target.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0]["AI估计匹配度(%)"], "96")
            self.assertEqual(rows[1]["地址"], "番禺区示例路2号")
            self.assertEqual(rows[2]["地址"], "")
            self.assertEqual(rows[2]["AI估计匹配度(%)"], "75")
            self.assertEqual(rows[2]["需核对"], "是")

    def test_request_contains_candidates_but_not_amap_key_and_is_cached(self):
        client = ai.DeepSeekFilter("synthetic-deepseek-key")
        decision = {"matches": [match(0, 95)], "reason": "仅测试"}
        payload = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(decision)}}]}
        client.opener = Mock()
        client.opener.open.return_value = io.BytesIO(json.dumps(payload).encode("utf-8"))
        client.screen(result(), "广州")
        request = client.opener.open.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(body["response_format"]["type"], "json_object")
        self.assertEqual(body["thinking"]["type"], "disabled")
        self.assertNotIn("synthetic-deepseek-key", request.data.decode())
        self.assertEqual(len(json.loads(body["messages"][1]["content"])["candidates"]), 3)
        client.screen(result(), "广州")
        self.assertEqual(client.opener.open.call_count, 1)

    def test_empty_amap_result_does_not_call_ai(self):
        client = ai.DeepSeekFilter("synthetic-key")
        client.opener = Mock()
        client.screen(summarize("没有的园区", []), "广州")
        client.opener.open.assert_not_called()

    def test_partial_ai_answer_rejected(self):
        client = ai.DeepSeekFilter("synthetic-key")
        client.opener = Mock()
        payload = {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}
        client.opener.open.return_value = io.BytesIO(json.dumps(payload).encode())
        with self.assertRaisesRegex(LookupError, "完整"):
            client.screen(result())

    def test_http_error_does_not_print_key(self):
        client = ai.DeepSeekFilter("synthetic-secret-key")
        client.opener = Mock()
        client.opener.open.side_effect = HTTPError("secret-key", 401, "secret-key", {}, None)
        with self.assertRaises(LookupError) as error:
            client.screen(result())
        self.assertNotIn("secret-key", str(error.exception))

    def test_compatible_endpoint_and_model_are_used_without_deepseek_fields(self):
        client = ai.DeepSeekFilter("synthetic-other-key", model="example-model",
                                   endpoint="https://api.example.com/v1/chat/completions")
        decision = {"matches": [match(0, 95)], "reason": "测试自定义接口"}
        payload = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(decision)}}]}
        client.opener = Mock()
        client.opener.open.return_value = io.BytesIO(json.dumps(payload).encode())
        client.screen(result())
        request = client.opener.open.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.example.com/v1/chat/completions")
        self.assertEqual(body["model"], "example-model")
        self.assertNotIn("thinking", body)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-other-key")

    def test_invalid_endpoint_never_includes_credentials_in_diagnostics(self):
        for endpoint in ("http://example.com/api", "https://user:synthetic-secret@example.com/api",
                         "https://example.com/api?key=synthetic-secret", "https://example.com:bad/api"):
            with self.assertRaises(LookupError) as error:
                ai.DeepSeekFilter("synthetic-secret", endpoint=endpoint)
            self.assertNotIn("synthetic-secret", str(error.exception))


if __name__ == "__main__":
    unittest.main()
