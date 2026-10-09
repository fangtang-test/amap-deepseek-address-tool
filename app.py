"""Small Windows desktop UI for name-to-address lookup."""
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from amap_lookup import (AmapClient, LookupError, export_csv, load_config, save_config,
                         selected_candidates, set_selected, text)
from ai_filter import DeepSeekFilter, DEFAULT_MODEL, ENDPOINT, load_settings, save_settings
from ui_theme import build_ui, update_summary


from batch_worker import BatchWorker


class App(BatchWorker):
    def __init__(self, root):
        self.root = root
        self.results = []
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.running = False
        self.client = None
        self.ai_client = None
        self.rows = {}
        self.retry_rows = {}
        self.last_city = ""
        config = load_config()
        ai_config = load_settings()
        build_ui(self, config, ai_config)
        self.ai_endpoint = text(ai_config.get("endpoint")) or ENDPOINT
        root.after(100, self.poll)

    def start(self, retry_failed=False):
        if self.running:
            return
        key, city = self.key.get().strip(), self.city.get().strip()
        names = list(dict.fromkeys(n.strip() for n in self.names.get("1.0", "end").splitlines() if n.strip()))
        if retry_failed:
            failed = [(i, r) for i, r in enumerate(self.results)
                      if r.get("lookup_failed") or (r.get("ai_failed") and not selected_candidates(r))]
            if not failed:
                self.status.set("没有失败项需要重试。“未找到”或“待确认”可以调整名称后重新查询。")
                return
            names = [r["query"] for _, r in failed]
            city = self.last_city
            self.retry_rows = {r["query"]: i for i, r in failed}
        else:
            self.retry_rows = {}
            self.last_city = city
        if not key or not names:
            messagebox.showinfo("先填写信息", "请填写 Web 服务 Key 和至少一个地点名称。", parent=self.root)
            return
        ai_key = self.ai_key.get().strip()
        ai_model = self.ai_model.get().strip() or DEFAULT_MODEL
        if self.ai_enabled.get() and not ai_key:
            messagebox.showinfo("填写 AI Key", "启用 AI 筛选需要独立的 DeepSeek API Key。", parent=self.root)
            return
        if len(names) > 500:
            messagebox.showinfo("名称较多", "每批最多查询 500 个地点，请分批粘贴。", parent=self.root)
            return
        try:
            save_config(key, city, self.remember.get())
            save_settings(ai_key, ai_model, self.ai_remember.get(), self.ai_enabled.get(), self.ai_endpoint)
        except OSError:
            messagebox.showerror("无法保存设置", "当前目录不可写，请把工具放到可写目录。", parent=self.root)
            return
        if self.client is None or self.client.key != key:
            self.client = AmapClient(key)
        if self.ai_enabled.get() and (self.ai_client is None or self.ai_client.key != ai_key or self.ai_client.model != ai_model):
            self.ai_client = DeepSeekFilter(ai_key, ai_model, endpoint=self.ai_endpoint)
        active_ai = self.ai_client if self.ai_enabled.get() else None
        if not retry_failed:
            self.tree.delete(*self.tree.get_children())
            self.results.clear()
            self.rows.clear()
            update_summary(self)
        self.progress.configure(value=0, maximum=len(names))
        self.stop.clear()
        self.running = True
        self.search_button.configure(state="disabled")
        self.retry_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status.set(f"正在查询 0 / {len(names)}…")
        threading.Thread(target=self.worker, args=(names, city, active_ai), daemon=True).start()

    def poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "result":
                    self.add_result(event[1])
                    self.progress.configure(value=event[2], maximum=event[3])
                    self.status.set(f"正在查询 {event[2]} / {event[3]}…")
                elif event[0] == "progress":
                    self.status.set(event[1])
                else:
                    self.running = False
                    self.search_button.configure(state="normal")
                    self.retry_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self.status.set(event[1])
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def add_result(self, result):
        index = self.retry_rows.get(result["query"])
        if index is None:
            index = len(self.results)
            self.results.append(result)
            row = self.tree.insert("", "end", iid=f"r{index}", text=result["query"],
                                   open=not bool(selected_candidates(result)))
            self.rows[row] = (index, None)
        else:
            row = f"r{index}"
            for child in self.tree.get_children(row):
                self.rows.pop(child, None)
                self.tree.delete(child)
            self.results[index] = result
            self.tree.item(row, open=not bool(selected_candidates(result)))
        for ci, candidate in enumerate(result["candidates"]):
            child = self.tree.insert(row, "end", text=candidate["name"],
                                     values=("", candidate["full_address"], "", "", ""))
            self.rows[child] = (index, ci)
        self.refresh_result(index)

    @staticmethod
    def confidence_label(candidate):
        value = candidate.get("ai_confidence")
        return f"{value:g}%（估计）" if value is not None else "—"

    def refresh_result(self, index):
        result = self.results[index]
        chosen = selected_candidates(result)
        address = "；".join(dict.fromkeys(p["address"] for p in chosen))
        rated = [p["ai_confidence"] for p in (chosen or result["candidates"]) if "ai_confidence" in p]
        score = (f"{min(rated):g}–{max(rated):g}%" if min(rated) != max(rated) else f"{rated[0]:g}%") if rated else "—"
        self.tree.item(f"r{index}", tags=("query",), values=(f"{len(chosen)}项", address, score, result["status"], result.get("ai_note", "")))
        for row in self.tree.get_children(f"r{index}"):
            ci = self.rows[row][1]
            candidate = result["candidates"][ci]
            checked = candidate in chosen
            confidence = candidate.get("ai_confidence")
            if not candidate["address"]:
                state = "无详细地址"
            elif checked:
                state = "已勾选" + ("；AI建议核对" if candidate.get("ai_review") or (confidence is not None and confidence < 90) else "")
            elif confidence is not None and confidence >= 60:
                state = "待确认，未勾选"
            elif confidence is not None:
                state = "AI不推荐"
            else:
                state = "未勾选"
            mark = ("☑" if checked else "☐") if candidate["address"] else "—"
            tag = "selected" if checked else "review" if confidence is not None and confidence >= 60 else "odd" if ci % 2 else "even"
            self.tree.item(row, tags=(tag,), values=(mark, candidate["full_address"], self.confidence_label(candidate), state,
                                       candidate.get("ai_reason", "")))
        update_summary(self)

    def click_checkbox(self, event):
        if self.tree.identify_column(event.x) != "#1":
            return
        row = self.tree.identify_row(event.y)
        if row in self.rows and self.rows[row][1] is not None:
            self.tree.focus(row)
            self.tree.selection_set(row)
            self.toggle_candidate(row)
            return "break"

    def select_candidate(self, event=None):
        if event is not None and getattr(event, "keysym", "") != "space":
            if self.tree.identify_column(event.x) == "#1":
                return "break"  # The first click already toggled the checkbox.
            row = self.tree.identify_row(event.y)
        else:
            row = self.tree.focus()
        self.toggle_candidate(row)
        if row in self.rows and self.rows[row][1] is None:
            result = self.results[self.rows[row][0]]
            messagebox.showinfo("查询详情", result["query"] + "\n\n" + result["status"] + "\n\n" + result.get("ai_note", ""), parent=self.root)
        return "break"

    def toggle_candidate(self, row):
        if row not in self.rows:
            return
        index, ci = self.rows[row]
        if ci is None:
            return
        result = self.results[index]
        candidate = result["candidates"][ci]
        if not candidate["address"]:
            self.status.set("这个候选没有详细地址，请选择其他候选。")
            return
        chosen = list(selected_candidates(result))
        if candidate in chosen:
            chosen.remove(candidate)
        else:
            chosen.append(candidate)
        set_selected(result, chosen, f"已手动勾选 {len(chosen)} 个" if chosen else "未勾选，地址留空")
        self.refresh_result(index)
        self.status.set(f"{result['query']}：已勾选 {len(chosen)} 个。" + candidate.get("ai_reason", candidate["full_address"]))

    def clear_selected(self):
        row = self.tree.focus()
        if row not in self.rows:
            self.status.set("先点击要清空的名称或候选。")
            return
        index = self.rows[row][0]
        result = self.results[index]
        set_selected(result, [], "未勾选，地址留空")
        self.refresh_result(index)
        self.status.set(f"已清空 {result['query']} 的勾选。")

    def copy_addresses(self):
        unique = {}
        for result in self.results:
            for candidate in selected_candidates(result):
                if candidate["address"]:
                    unique.setdefault(candidate["full_address"], candidate["address"])
        values = list(unique.values())
        if not values:
            self.status.set("没有已勾选的地址。请先查询并勾选候选。")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(values))
        self.status.set(f"已复制 {len(values)} 条地址。")

    def export(self):
        if not self.results:
            self.status.set("请先查询地址。")
            return
        path = filedialog.asksaveasfilename(parent=self.root, title="导出查询结果", defaultextension=".csv",
                                          initialfile="高德地址查询结果.csv", filetypes=[("CSV 表格", "*.csv")])
        if path:
            try:
                export_csv(path, self.results)
            except OSError:
                messagebox.showerror("导出失败", "请关闭正在打开的同名表格，或选择其他保存目录。", parent=self.root)
                return
            self.status.set("已导出，每个勾选地点一行；未勾选的名称地址留空，AI 匹配度和依据一并保存。")


def run_desktop():
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except (ImportError, AttributeError, OSError):
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


def run():
    from web_app import run as run_browser
    run_browser()


if __name__ == "__main__":
    import sys
    if "--desktop" in sys.argv:
        run_desktop()
    else:
        run()
