"""Direct HTTPS requests, bounded retries, and credential-free diagnostics."""
import http.client
import json
import socket
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener


class LookupError(Exception):
    def __init__(self, message, *, retryable=False, stop_batch=True, category=""):
        super().__init__(message)
        self.retryable = retryable
        self.stop_batch = stop_batch
        self.category = category


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def direct_opener():
    # AMap/DeepSeek are reached directly; stale system HTTP proxy settings are ignored.
    return build_opener(ProxyHandler({}), NoRedirect())


def classify_error(exc, service):
    if isinstance(exc, HTTPError):
        messages = {
            401: "Key 无效或已过期", 402: "可用余额不足", 403: "接口拒绝访问，请检查权限",
            429: "请求频率超限", 500: "服务端暂时异常", 502: "服务网关暂时异常",
            503: "服务暂不可用", 504: "服务网关响应超时",
        }
        transient = exc.code in {429, 500, 502, 503, 504}
        return LookupError(f"{service}：{messages.get(exc.code, '接口请求失败')}（HTTP {exc.code}）。",
                           retryable=transient, stop_batch=exc.code in {401, 402, 403, 429},
                           category="http")
    reason = exc.reason if isinstance(exc, URLError) else exc
    if isinstance(reason, ssl.SSLCertVerificationError):
        return LookupError(f"{service} HTTPS 证书校验失败，请检查系统时间或网络拦截。",
                           stop_batch=False, category="certificate")
    if isinstance(reason, socket.gaierror):
        message, category = "域名解析失败（DNS）", "dns"
    elif isinstance(reason, (TimeoutError, socket.timeout)):
        message, category = "连接或响应超时", "timeout"
    elif isinstance(reason, ConnectionRefusedError):
        message, category = "目标连接被拒绝", "refused"
    elif isinstance(reason, (ConnectionResetError, http.client.RemoteDisconnected, http.client.IncompleteRead)):
        message, category = "连接被中断或响应未读完", "disconnected"
    elif isinstance(reason, ssl.SSLError):
        message, category = "HTTPS 握手失败", "tls"
    else:
        message, category = "连接失败", "connection"
    # Only expose numeric OS codes, never exception text or URLs containing credentials.
    code = getattr(reason, "winerror", None) or getattr(reason, "errno", None)
    suffix = f"（系统错误 {code}）" if isinstance(code, int) else ""
    return LookupError(f"{service}{message}{suffix}。", retryable=True,
                       stop_batch=False, category=category)


def request_json(request, open_request, service, *, timeout, attempts=3,
                 on_retry=None, cancel_event=None):
    for attempt in range(1, attempts + 1):
        if cancel_event is not None and cancel_event.is_set():
            raise LookupError("已停止查询。", stop_batch=False, category="cancelled")
        try:
            with open_request(request, timeout=timeout) as response:
                return json.loads(response.read(2_000_000).decode("utf-8"))
        except (HTTPError, URLError, OSError, http.client.HTTPException) as exc:
            failure = classify_error(exc, service)
        except (ValueError, UnicodeError):
            failure = LookupError(f"{service}返回内容不是有效 JSON。", retryable=True,
                                  stop_batch=False, category="response")
        if not failure.retryable or attempt >= attempts:
            if attempt > 1:
                failure.args = (str(failure) + f"已尝试 {attempt} 次。",)
            raise failure from None
        if on_retry is not None:
            on_retry(f"{failure}正在重试（第 {attempt + 1}/{attempts} 次）…")
        delay = 0.8 * attempt
        if cancel_event is not None:
            if cancel_event.wait(delay):
                raise LookupError("已停止查询。", stop_batch=False, category="cancelled")
        else:
            time.sleep(delay)
