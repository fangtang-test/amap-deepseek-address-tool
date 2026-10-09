"""Local-only browser UI. Python standard library, no cloud hosting required."""
import json
import os
from pathlib import Path
import queue
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from amap_lookup import AmapClient, load_config, save_config, text
from ai_filter import DeepSeekFilter, DEFAULT_MODEL, ENDPOINT, load_settings, save_settings, validate_endpoint
from amap_lookup import LookupError
from batch_worker import BatchWorker

ROOT = Path(__file__).resolve().parent


class Service(BatchWorker):
    def __init__(self):
        self.client = None
        self.ai_client = None
        self.stop = threading.Event()
        self.events = queue.Queue()
        self.lock = threading.Lock()
        self.running = False
        self.job = ""
        self.history = []

    def start(self, data):
        names = data.get("names")
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise ValueError("请填写地点名称，一行一个。")
        names = list(dict.fromkeys(n.strip() for n in names if n.strip()))
        if not 1 <= len(names) <= 500 or any(len(n) > 500 for n in names):
            raise ValueError("每批需填写 1–500 个名称，每个名称不超过 500 字。")
        config, settings = load_config(), load_settings()
        key = text(data.get("key")) or os.environ.get("AMAP_KEY") or text(config.get("key")) or (self.client.key if self.client else "")
        city = text(data.get("city"))
        model = text(data.get("model")) or os.environ.get("AI_MODEL") or text(settings.get("model")) or DEFAULT_MODEL
        endpoint = validate_endpoint(data.get("endpoint") or os.environ.get("AI_ENDPOINT") or settings.get("endpoint") or ENDPOINT)
        stored_endpoint = text(settings.get("endpoint")) or ENDPOINT
        env_endpoint = os.environ.get("AI_ENDPOINT") or ENDPOINT
        ai_key = (text(data.get("ai_key"))
                  or (os.environ.get("AI_API_KEY", "") if endpoint == env_endpoint else "")
                  or (os.environ.get("DEEPSEEK_API_KEY", "") if endpoint == ENDPOINT else "")
                  or (text(settings.get("key")) if endpoint == stored_endpoint else "")
                  or (self.ai_client.key if self.ai_client and self.ai_client.endpoint == endpoint else ""))
        enabled = bool(data.get("ai_enabled"))
        if not key:
            raise ValueError("请先在「连接设置」中填写高德 Web 服务 Key。")
        if enabled and not ai_key:
            raise ValueError("启用 AI 需要所选服务的独立 API Key。")
        if enabled and endpoint != ENDPOINT and not text(data.get("model")) and not os.environ.get("AI_MODEL"):
            raise ValueError("请填写所选 AI 接口实际支持的模型名称。")
        with self.lock:
            if self.running:
                raise ValueError("当前查询尚未结束，请先停止或等待完成。")
            save_config(key, city, bool(data.get("remember")))
            save_settings(ai_key, model, bool(data.get("ai_remember")), enabled, endpoint)
            if self.client is None or self.client.key != key:
                self.client = AmapClient(key)
            if enabled and (self.ai_client is None or self.ai_client.key != ai_key or self.ai_client.model != model or self.ai_client.endpoint != endpoint):
                self.ai_client = DeepSeekFilter(ai_key, model, endpoint=endpoint)
            self.stop.clear()
            self.events = queue.Queue()
            self.history = []
            self.job = secrets.token_hex(8)
            self.running = True
            threading.Thread(target=self._work, args=(names, city, self.ai_client if enabled else None), daemon=True).start()
            return {"job": self.job, "total": len(names)}

    def _work(self, names, city, ai_client):
        try:
            self.worker(names, city, ai_client)
        finally:
            with self.lock:
                self.running = False

    def snapshot(self, job, cursor):
        with self.lock:
            if job != self.job:
                raise ValueError("查询会话已更新，请刷新页面。")
            while not self.events.empty():
                self.history.append(self.events.get_nowait())
            return {"events": self.history[max(0, cursor):], "cursor": len(self.history), "running": self.running}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Local query names and credentials never enter access logs.

    def respond(self, data, status=200, mime="application/json; charset=utf-8"):
        content = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, dict) else data
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(content)

    def authorized(self, api=True):
        host = self.headers.get("Host", "")
        if host != f"127.0.0.1:{self.server.server_port}":
            self.respond({"error": "不允许的访问来源。"}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{host}":
            self.respond({"error": "不允许跨站访问。"}, 403)
            return False
        if api and not secrets.compare_digest(self.headers.get("X-App-Token", ""), self.server.token):
            self.respond({"error": "请从工具启动页面访问。"}, 403)
            return False
        return True

    def do_GET(self):
        path = urlsplit(self.path).path
        if not self.authorized(api=path != "/"):
            return
        if path == "/":
            html = (ROOT / "web/index.html").read_text(encoding="utf-8").replace("__APP_TOKEN__", self.server.token)
            self.respond(html.encode(), mime="text/html; charset=utf-8")
        elif path == "/api/settings":
            config, settings = load_config(), load_settings()
            endpoint = os.environ.get("AI_ENDPOINT") or text(settings.get("endpoint")) or ENDPOINT
            stored_endpoint = text(settings.get("endpoint")) or ENDPOINT
            self.respond({"city": text(config.get("city")), "model": os.environ.get("AI_MODEL") or text(settings.get("model")) or DEFAULT_MODEL,
                          "endpoint": os.environ.get("AI_ENDPOINT") or text(settings.get("endpoint")) or ENDPOINT,
                          "ai_enabled": bool(settings.get("enabled")),
                          "has_key": bool(config.get("key") or os.environ.get("AMAP_KEY") or self.server.service.client),
                          "has_ai_key": bool((settings.get("key") if endpoint == stored_endpoint else "")
                                             or os.environ.get("AI_API_KEY")
                                             or (os.environ.get("DEEPSEEK_API_KEY") if endpoint == ENDPOINT else "")
                                             or (self.server.service.ai_client if self.server.service.ai_client and self.server.service.ai_client.endpoint == endpoint else "")),
                          "remember": bool(config.get("key")), "ai_remember": bool(settings.get("key"))})
        else:
            self.respond({"error": "页面不存在。"}, 404)

    def do_POST(self):
        if not self.authorized():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2_000_000:
                raise ValueError("请求大小不符合要求。")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("请求格式不正确。")
            if self.path == "/api/query":
                result = self.server.service.start(data)
            elif self.path == "/api/poll":
                result = self.server.service.snapshot(text(data.get("job")), int(data.get("cursor", 0)))
            elif self.path == "/api/stop":
                if data.get("job") != self.server.service.job:
                    raise ValueError("当前查询会话已更新。")
                self.server.service.stop.set()
                result = {"ok": True}
            else:
                self.respond({"error": "接口不存在。"}, 404)
                return
            self.respond(result)
        except LookupError as exc:
            self.respond({"error": str(exc)}, 400)
        except (ValueError, TypeError) as exc:
            # Validation messages contain no credentials or raw upstream responses.
            message = str(exc) if type(exc) is ValueError and not isinstance(exc, json.JSONDecodeError) else "请求格式不正确。"
            self.respond({"error": message}, 400)
        except OSError:
            self.respond({"error": "无法保存设置，请把工具放在可写目录。"}, 500)
        except Exception:
            self.respond({"error": "操作未完成，请重新启动工具。"}, 500)


def make_server(port=0):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.token = secrets.token_urlsafe(32)
    server.service = Service()
    return server


def run():
    server = make_server()
    url = f"http://127.0.0.1:{server.server_port}/"
    print("地点查询工作台已启动：" + url)
    print("关闭此终端可退出工具。界面只在本机提供服务。")
    threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.service.stop.set()
        server.server_close()


if __name__ == "__main__":
    run()
