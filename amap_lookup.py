"""Reusable AMap name-to-address lookup; Python 3.10+, standard library only."""
from __future__ import annotations

import argparse
import csv
from difflib import SequenceMatcher
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
import unicodedata
from urllib.parse import urlencode
from urllib.request import Request
from transport import LookupError, direct_opener, request_json

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.json"
ENDPOINT = "https://restapi.amap.com/v5/place/text"
urlopen = direct_opener().open


def text(value):
    # AMap sometimes returns [] for absent fields.
    return value.strip() if isinstance(value, str) else ""


def normalize(value):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text(value))).casefold()


def name_without_city(name, city):
    value = normalize(name)
    city = normalize(city)
    if city and not city.isdigit():
        for prefix in sorted({city, city.removesuffix("市")}, key=len, reverse=True):
            if prefix and value.startswith(prefix):
                value = value[len(prefix):].removeprefix("市")
                break
    return value


def addresses(poi):
    street = text(poi.get("address"))
    district = text(poi.get("adname"))
    if not street:
        return "", ""  # A district alone is not a detailed address.
    # Avoid repeating administrative units already present in the API address.
    parts = [text(poi.get(k)) for k in ("pname", "cityname", "adname")]
    short = street if not district or district in street else district + street
    full = street
    for part in reversed(parts):
        if part and part not in full:
            full = part + full
    return short, full


def rank_candidates(pois, query, city):
    needle = name_without_city(query, city)
    ranked = []
    seen = set()
    for poi in pois:
        if not isinstance(poi, dict) or not text(poi.get("name")):
            continue
        short, full = addresses(poi)
        identity = text(poi.get("id")) or (text(poi.get("name")), full)
        if identity in seen:
            continue
        seen.add(identity)
        name = text(poi.get("name"))
        candidate = name_without_city(name, city or text(poi.get("cityname")))
        score = SequenceMatcher(None, needle, candidate).ratio()
        ranked.append({"name": name, "address": short, "full_address": full,
                       "id": text(poi.get("id")), "city": text(poi.get("cityname")),
                       "type": text(poi.get("type")), "parent": text(poi.get("parent")),
                       "exact": bool(needle) and needle == candidate, "score": score})
    # Preserve AMap's order when local name scores tie.
    return sorted(ranked, key=lambda p: (p["exact"], p["score"]), reverse=True)


def summarize(query, candidates):
    # Each lookup owns its candidate metadata; UI/AI changes must not mutate the cache.
    candidates = [dict(p) for p in candidates]
    exact = [p for p in candidates if p["exact"]]
    unique_addresses = {p["full_address"] for p in exact if p["address"]}
    selected = None
    if exact and all(p["address"] for p in exact) and len(unique_addresses) == 1:
        selected = exact[0]
        status = "名称匹配"
    elif not candidates:
        status = "未找到"
    elif not any(p["address"] for p in candidates):
        status = "高德未返回详细地址"
    else:
        status = "待选择"
    return {"query": query, "status": status, "selected": selected,
            "selected_items": [selected] if selected else [], "candidates": candidates}


def selected_candidates(result):
    if "selected_items" in result:
        return result["selected_items"]
    return [result["selected"]] if result.get("selected") else []


def set_selected(result, candidates, status):
    result["selected_items"] = list(candidates)
    # Keep the legacy single-result field for code written against v1.
    result["selected"] = candidates[0] if candidates else None
    result["status"] = status


ERROR_HINTS = {
    "10001": "Key 无效，请检查是否复制完整。",
    "10002": "没有搜索服务权限，请检查 Web 服务 Key 和控制台权限。",
    "10003": "调用额度已用完，请检查高德控制台的用量。",
    "10004": "访问过于频繁，请稍后重试。",
    "10005": "Key 的 IP 白名单限制了访问，请检查控制台设置。",
    "10007": "Key 签名校验失败，请检查控制台的签名设置。",
    "10009": "Key 平台类型不匹配，请选择 Web 服务类型。",
    "10012": "服务权限不足，请检查个人认证和搜索服务权限。",
    "10013": "Key 已被删除，请创建新的 Web 服务 Key。",
    "10014": "访问过于频繁，请稍后重试。",
    "10019": "服务每秒请求数超限，请稍后重试。",
    "10020": "Key 每秒请求数超限，请稍后重试。",
    "10021": "账号每秒请求数超限，请稍后重试；若配额为 0 请检查个人认证。",
    "10044": "调用额度不足，请检查高德控制台的用量。",
    "40000": "可用余额或配额不足，请检查高德控制台的用量。",
}


class AmapClient:
    def __init__(self, key, timeout=20):
        self.key = text(key)
        self.timeout = timeout
        self._last_request = 0.0
        self._lock = threading.Lock()
        self._cache = {}

    def lookup(self, query, city="", *, on_retry=None, cancel_event=None):
        query, city = text(query), text(city)
        if not self.key:
            raise LookupError("请先填写高德 Web 服务 Key。")
        if not query:
            raise LookupError("请输入地点名称。", stop_batch=False)
        if len(query) > 80:
            raise LookupError("地点名称不能超过 80 个字符。", stop_batch=False)
        cache_key = (query, city)
        with self._lock:
            if cache_key in self._cache:
                return summarize(query, self._cache[cache_key])
            delay = 0.4 - (time.monotonic() - self._last_request)
            if delay > 0:
                if cancel_event is not None:
                    if cancel_event.wait(delay):
                        raise LookupError("已停止查询。", stop_batch=False, category="cancelled")
                else:
                    time.sleep(delay)
            params = {"key": self.key, "keywords": query, "page_size": 25,
                      "page_num": 1, "output": "json"}
            if city:
                params.update(region=city, city_limit="true")
            request = Request(ENDPOINT + "?" + urlencode(params),
                              headers={"User-Agent": "AMapAddressLearningTool/1.0"})
            self._last_request = time.monotonic()
            payload = request_json(request, urlopen, "高德", timeout=self.timeout,
                                   on_retry=on_retry, cancel_event=cancel_event)
            if not isinstance(payload, dict):
                raise LookupError("高德接口返回格式异常。", stop_batch=False)
            if str(payload.get("status")) != "1":
                code = str(payload.get("infocode", "未知"))
                hint = ERROR_HINTS.get(code, "请检查高德控制台的 Key、权限和用量。")
                raise LookupError(f"高德查询失败（{code}）：{hint}",
                                  stop_batch=code not in {"20000", "20012", "20003"}, category="api")
            pois = payload.get("pois", [])
            if not isinstance(pois, list):
                raise LookupError("高德接口的地点列表格式异常。", stop_batch=False)
            candidates = rank_candidates(pois, query, city)
            self._cache[cache_key] = candidates
            return summarize(query, candidates)


def load_config():
    try:
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(key, city, remember):
    data = {"city": city}
    if remember:
        data["key"] = key
    # Only stores a Key when the user explicitly checks Remember.
    temp = CONFIG.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(CONFIG)


def export_csv(path, results):
    def cell(value):
        value = str(value or "")
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
    with open(path, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["输入名称", "地址", "匹配地点", "完整地址", "状态", "高德POI ID",
                         "AI估计匹配度(%)", "需核对", "筛选依据"])
        for result in results:
            items = selected_candidates(result)
            if not items:
                # Review suggestions are kept without filling an address into the final result.
                suggestions = [p for p in result.get("candidates", []) if p.get("ai_confidence", 0) >= 60]
                best = max(suggestions, key=lambda p: p["ai_confidence"], default={})
                writer.writerow([cell(result["query"]), "", "", "", cell(result["status"]), "",
                                 best.get("ai_confidence", ""), "是" if suggestions else "",
                                 cell(result.get("ai_note", ""))])
            for selected in items:
                confidence = selected.get("ai_confidence", "")
                review = "是" if selected.get("ai_review") or (confidence != "" and confidence < 90) else ""
                writer.writerow([cell(result["query"]), cell(selected.get("address")),
                                 cell(selected.get("name")), cell(selected.get("full_address")),
                                 cell(result["status"]), cell(selected.get("id")), confidence, review,
                                 cell(selected.get("ai_reason", ""))])


def main():
    parser = argparse.ArgumentParser(description="高德地点名称转地址；不传名称时打开图形界面。")
    parser.add_argument("names", nargs="*")
    parser.add_argument("--city", default=None, help="城市名或行政区划编码；留空查全国")
    parser.add_argument("--input", type=Path, help="UTF-8 文本文件，一行一个地点名称")
    parser.add_argument("--output", type=Path, help="将查询结果导出 CSV")
    parser.add_argument("--json", action="store_true", help="输出 JSON（包含待选择候选）")
    parser.add_argument("--ai", action="store_true", help="启用本机配置的 DeepSeek 筛选")
    args = parser.parse_args()
    if not args.names and not args.input:
        from app import run
        run()
        return 0
    config = load_config()
    city = args.city if args.city is not None else text(config.get("city"))
    client = AmapClient(os.environ.get("AMAP_KEY") or text(config.get("key")))
    ai_client = None
    ai_failure = ""
    if args.ai:
        from ai_filter import DeepSeekFilter, DEFAULT_MODEL, ENDPOINT as AI_ENDPOINT, load_settings
        settings = load_settings()
        ai_endpoint = os.environ.get("AI_ENDPOINT") or text(settings.get("endpoint")) or AI_ENDPOINT
        stored_endpoint = text(settings.get("endpoint")) or AI_ENDPOINT
        ai_key = (os.environ.get("AI_API_KEY")
                  or (os.environ.get("DEEPSEEK_API_KEY") if ai_endpoint == AI_ENDPOINT else "")
                  or (text(settings.get("key")) if ai_endpoint == stored_endpoint else ""))
        if not ai_key:
            print("启用 AI 需要在界面填写 AI Key 或设置 AI_API_KEY / DEEPSEEK_API_KEY。", file=sys.stderr)
            return 1
        ai_client = DeepSeekFilter(ai_key, os.environ.get("AI_MODEL") or text(settings.get("model")) or DEFAULT_MODEL,
                                   endpoint=ai_endpoint)
    names = list(args.names)
    if args.input:
        try:
            names += args.input.read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeError):
            print("无法读取输入文件，请使用 UTF-8 文本。", file=sys.stderr)
            return 1
    names = list(dict.fromkeys(n.strip() for n in names if n.strip()))
    if not names:
        print("输入文件没有地点名称。", file=sys.stderr)
        return 1
    results = []
    consecutive_failures = 0
    for index, name in enumerate(names):
        try:
            result = client.lookup(name, city)
        except LookupError as exc:
            result = {"query": name, "status": str(exc), "selected": None, "selected_items": [],
                      "candidates": [], "lookup_failed": True, "ai_note": str(exc)}
            results.append(result)
            consecutive_failures += 1
            if exc.stop_batch or consecutive_failures >= 3:
                results.extend({"query": n, "status": "未查询（服务不可用，本批已暂停）",
                                "selected": None, "candidates": [], "lookup_failed": True} for n in names[index + 1:])
                break
            continue
        consecutive_failures = 0
        if ai_client is not None and result["candidates"]:
            if not ai_failure:
                try:
                    ai_client.screen(result, city)
                except LookupError as exc:
                    if exc.stop_batch:
                        ai_failure = str(exc)
                    set_selected(result, [], "AI未完成，待人工选择")
                    result["ai_note"] = str(exc)
                    result["ai_failed"] = True
            if ai_failure:
                set_selected(result, [], "AI未完成，待人工选择")
                result["ai_note"] = ai_failure
        results.append(result)
    if args.output:
        export_csv(args.output, results)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for result in results:
            if selected_candidates(result):
                for candidate in selected_candidates(result):
                    print(candidate["address"])
            else:
                print(f'{result["query"]}：{result["status"]}')
                for p in result["candidates"][:5]:
                    print(f'  {p["name"]} — {p["full_address"] or "无详细地址"}')
    return 0 if all(selected_candidates(r) for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
