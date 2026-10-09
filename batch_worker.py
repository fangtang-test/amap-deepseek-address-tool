"""Shared batch lookup engine for desktop and browser interfaces."""
from amap_lookup import LookupError, selected_candidates, set_selected


class BatchWorker:
    def worker(self, names, city, ai_client=None):
        ai_failure = ""
        consecutive_failures = 0
        consecutive_ai_failures = 0
        failures = 0

        def mark_unqueried(start, reason):
            for j in range(start, len(names)):
                self.events.put(("result", {"query": names[j], "status": reason,
                                 "selected": None, "selected_items": [], "candidates": [],
                                 "lookup_failed": True, "ai_note": reason}, j + 1, len(names)))

        for i, name in enumerate(names):
            if self.stop.is_set():
                mark_unqueried(i, "未查询（已停止，可重试）")
                break
            def retry_progress(message, current=name):
                self.events.put(("progress", current + "：" + message))
            try:
                result = self.client.lookup(name, city, on_retry=retry_progress, cancel_event=self.stop)
            except LookupError as exc:
                failures += 1
                consecutive_failures += 1
                self.events.put(("result", {"query": name, "status": str(exc), "selected": None,
                                 "selected_items": [], "candidates": [], "lookup_failed": True,
                                 "ai_note": str(exc)}, i + 1, len(names)))
                if self.stop.is_set():
                    mark_unqueried(i + 1, "未查询（已停止，可重试）")
                    break
                if exc.stop_batch or consecutive_failures >= 3:
                    reason = "未查询（服务不可用，本批暂停，可重试）"
                    mark_unqueried(i + 1, reason)
                    self.events.put(("done", "本批查询已暂停：" + str(exc) + " 已保留成功结果，其余可点“重试失败项”。"))
                    return
                continue
            except Exception:
                mark_unqueried(i, "未完成（程序异常，可重试）")
                self.events.put(("done", "查询出现异常，已保留成功结果，其余可重试。"))
                return
            consecutive_failures = 0
            if ai_client is not None and result["candidates"]:
                item_ai_error = ai_failure
                if not ai_failure and not self.stop.is_set():
                    self.events.put(("progress", f"高德已返回候选，AI 正在筛选 {i + 1} / {len(names)}：{name}…"))
                    try:
                        ai_client.screen(result, city, on_retry=retry_progress, cancel_event=self.stop)
                        consecutive_ai_failures = 0
                    except LookupError as exc:
                        item_ai_error = str(exc)
                        consecutive_ai_failures += 1
                        if exc.stop_batch or consecutive_ai_failures >= 3:
                            ai_failure = item_ai_error
                    except Exception:
                        item_ai_error = "AI 筛选出现异常，请稍后重试。"
                        consecutive_ai_failures += 1
                        if consecutive_ai_failures >= 3:
                            ai_failure = item_ai_error
                if item_ai_error or self.stop.is_set():
                    failures += 1
                    set_selected(result, [], "AI未完成，待人工选择")
                    result["ai_note"] = item_ai_error or "已停止 AI 筛选。"
                    result["ai_failed"] = True
            self.events.put(("result", result, i + 1, len(names)))
        message = "已停止。已取得的结果可以复制或导出。" if self.stop.is_set() else "查询完成。可多选候选，AI 不确定的地点留空待确认。"
        if ai_failure:
            message += " AI 已暂停：" + ai_failure
        if failures:
            message += f" 有 {failures} 项请求失败，可点“重试失败项”；成功结果和勾选会保留。"
        self.events.put(("done", message))
