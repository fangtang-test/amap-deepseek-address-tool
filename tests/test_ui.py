"""Own-app integration checks using synthetic data and a hidden Tk window."""
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import app
from amap_lookup import LookupError, rank_candidates, summarize


class UiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        with patch("app.load_config", return_value={}), patch("app.load_settings", return_value={}):
            self.ui = app.App(self.root)

    def tearDown(self):
        self.root.destroy()

    def test_candidate_selection_and_copy(self):
        candidates = rank_candidates([{"name": "测试园文化旅游区", "address": "示例路10号",
                                      "pname": "广东省", "cityname": "广州市", "adname": "番禺区"}],
                                     "测试园文化创意园", "广州")
        self.ui.add_result(summarize("测试园文化创意园", candidates))
        child = self.ui.tree.get_children("r0")[0]
        self.ui.tree.focus(child)
        self.ui.select_candidate()
        self.assertEqual(self.ui.results[0]["status"], "已手动勾选 1 个")
        self.ui.copy_addresses()
        self.assertEqual(self.root.clipboard_get(), "番禺区示例路10号")

    def test_worker_failure_stops_batch(self):
        self.ui.client = Mock()
        self.ui.client.lookup.side_effect = LookupError("Key 无效")
        self.ui.worker(["测试园一", "测试园二"], "广州")
        self.ui.poll()
        self.assertEqual(self.ui.client.lookup.call_count, 1)
        self.assertEqual(len(self.ui.results), 2)
        self.assertIn("Key 无效", self.ui.results[0]["status"])
        self.assertIn("暂停", self.ui.status.get())

    def test_empty_street_cannot_be_selected(self):
        candidates = rank_candidates([{"name": "测试园", "address": [], "adname": "番禺区"}], "测试园", "广州")
        self.ui.add_result(summarize("测试园", candidates))
        self.ui.tree.focus(self.ui.tree.get_children("r0")[0])
        self.ui.select_candidate()
        self.assertIsNone(self.ui.results[0]["selected"])

    def test_multiple_candidates_can_be_checked_and_automatic_match_unchecked(self):
        candidates = rank_candidates([
            {"id": "synthetic-exact", "name": "测试文化创意园", "address": "示例路口西北40米", "adname": "番禺区"},
            {"id": "synthetic-scenic", "name": "测试文化创意产业园景区", "address": "示例路264号", "adname": "番禺区"},
        ], "测试文化创意园", "广州")
        self.ui.add_result(summarize("测试文化创意园", candidates))
        self.assertEqual(self.ui.results[0]["status"], "名称匹配")
        children = self.ui.tree.get_children("r0")
        self.assertEqual(len(children), 2)
        self.ui.tree.focus(children[1])
        self.ui.select_candidate()
        self.assertEqual(len(self.ui.results[0]["selected_items"]), 2)
        self.ui.copy_addresses()
        self.assertEqual(self.root.clipboard_get(), "番禺区示例路口西北40米\n番禺区示例路264号")
        self.ui.tree.focus(children[0])
        self.ui.select_candidate()
        self.assertEqual(self.ui.results[0]["selected"]["address"], "番禺区示例路264号")
        self.assertEqual(self.ui.results[0]["status"], "已手动勾选 1 个")
        self.ui.tree.focus(children[1])
        self.ui.select_candidate()
        self.assertIsNone(self.ui.results[0]["selected"])
        self.assertEqual(self.ui.results[0]["selected_items"], [])

    def test_copy_includes_checked_places_from_multiple_queries(self):
        for i in range(2):
            candidates = rank_candidates([{"name": f"测试园{i}", "address": f"示例路{i}号", "adname": "番禺区"}], f"测试园{i}", "广州")
            self.ui.add_result(summarize(f"测试园{i}", candidates))
        self.ui.tree.selection_set("r0")
        self.ui.copy_addresses()
        self.assertEqual(self.root.clipboard_get(), "番禺区示例路0号\n番禺区示例路1号")

    def test_medium_confidence_is_visible_but_not_checked(self):
        from ai_filter import apply_decision
        candidates = rank_candidates([{"name": "测试园", "address": "示例路1号", "adname": "番禺区"}], "测试园", "广州")
        result = summarize("测试园", candidates)
        apply_decision(result, {"matches": [{"candidate_index": 0, "confidence": 75, "needs_review": True, "reason": "名称近似，缺乏主体证据"}], "reason": "需人工核对"})
        self.ui.add_result(result)
        child = self.ui.tree.get_children("r0")[0]
        self.assertEqual(self.ui.tree.set(child, "pick"), "☐")
        self.assertIn("75%", self.ui.tree.set(child, "confidence"))
        self.assertIn("待确认", self.ui.tree.set(child, "status"))
        self.ui.tree.focus(child)
        self.ui.select_candidate()
        self.assertIn("AI建议核对", self.ui.tree.set(child, "status"))

    def test_ai_error_keeps_addresses_empty_and_stops_repeated_ai_calls(self):
        self.ui.client = Mock()
        def fake_lookup(name, city, **kwargs):
            candidates = rank_candidates([{"name": name, "address": "示例路1号", "adname": "番禺区"}], name, city)
            return summarize(name, candidates)
        self.ui.client.lookup.side_effect = fake_lookup
        ai = Mock()
        ai.screen.side_effect = LookupError("AI 余额不足")
        self.ui.worker(["测试园一", "测试园二"], "广州", ai)
        self.ui.poll()
        self.assertEqual(ai.screen.call_count, 1)
        self.assertEqual(len(self.ui.results), 2)
        self.assertTrue(all(not r["selected_items"] for r in self.ui.results))
        self.assertIn("AI 余额不足", self.ui.status.get())

    def test_one_network_failure_does_not_stop_other_names(self):
        candidates = rank_candidates([{"name": "成功园区", "address": "示例路1号"}], "成功园区", "广州")
        self.ui.client = Mock()
        self.ui.client.lookup.side_effect = [LookupError("高德连接超时，已尝试3次。", stop_batch=False), summarize("成功园区", candidates)]
        self.ui.worker(["失败园区", "成功园区"], "广州")
        self.ui.poll()
        self.assertEqual(self.ui.client.lookup.call_count, 2)
        self.assertTrue(self.ui.results[0]["lookup_failed"])
        self.assertEqual(self.ui.results[1]["selected"]["address"], "示例路1号")
        self.assertIn("重试失败项", self.ui.status.get())

    def test_retry_replaces_failed_row_without_losing_successful_selection(self):
        good = summarize("成功园区", rank_candidates([{"name": "成功园区", "address": "示例路1号"}], "成功园区", "广州"))
        self.ui.add_result(good)
        self.ui.add_result({"query": "失败园区", "status": "连接超时", "selected": None, "selected_items": [], "candidates": [], "lookup_failed": True})
        self.ui.retry_rows = {"失败园区": 1}
        recovered = summarize("失败园区", rank_candidates([{"name": "失败园区", "address": "示例路2号"}], "失败园区", "广州"))
        self.ui.add_result(recovered)
        self.assertEqual(len(self.ui.results), 2)
        self.assertEqual(self.ui.results[0]["selected_items"], good["selected_items"])
        self.assertEqual(self.ui.results[1]["selected"]["address"], "示例路2号")
        self.assertEqual(len(self.ui.tree.get_children()), 2)

    def test_three_consecutive_failures_pause_and_mark_remaining_items(self):
        self.ui.client = Mock()
        self.ui.client.lookup.side_effect = LookupError("高德连接超时", stop_batch=False)
        self.ui.worker(["一", "二", "三", "四"], "广州")
        self.ui.poll()
        self.assertEqual(self.ui.client.lookup.call_count, 3)
        self.assertEqual(len(self.ui.results), 4)
        self.assertIn("未查询", self.ui.results[3]["status"])
        self.assertIn("暂停", self.ui.status.get())

    def test_temporary_ai_failure_does_not_disable_following_names(self):
        self.ui.client = Mock()
        def fake_lookup(name, city, **kwargs):
            return summarize(name, rank_candidates([{"name": name, "address": "示例路1号"}], name, city))
        self.ui.client.lookup.side_effect = fake_lookup
        ai = Mock()
        ai.screen.side_effect = [LookupError("AI响应超时", stop_batch=False), None]
        self.ui.worker(["一", "二"], "广州", ai)
        self.ui.poll()
        self.assertEqual(ai.screen.call_count, 2)
        self.assertTrue(self.ui.results[0]["ai_failed"])
        self.assertEqual(self.ui.results[0]["selected_items"], [])
        self.assertNotIn("ai_failed", self.ui.results[1])


if __name__ == "__main__":
    unittest.main()
