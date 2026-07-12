"""Chrome DevTools Protocol 客户端：通过本地 Chrome 远程调试拉取数据。

设计目标：
  - 仅依赖 stdlib + websockets（已在依赖里），便于跨平台打包
  - 只暴露 fetcher 真正用到的高层 API：找标签 / 开标签 / 注入 JS
  - 异常类型明确（CDPError / CDPRefused / CDPNoTab / CDPEvalError），
    上层（fetchers/grok.py + main.py）按类区分处理

前置要求（启动 Chrome 时附上；--user-data-dir 指到本机默认配置目录，
这样能复用正在用的 Chrome 的登录态）：
  Windows (PowerShell)：
    & "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" `
       --remote-debugging-port=9222 `
       --user-data-dir="$env:LOCALAPPDATA\\Google\\Chrome\\User Data"
  macOS：
    open -a "Google Chrome" --args \
       --remote-debugging-port=9222 \
       --user-data-dir="$HOME/Library/Application Support/Google/Chrome"

为什么必须 --user-data-dir 指向默认那个目录：
  Chrome 默认每个新进程用独立 user data 目录。指向本机默认那个，调试
  Chrome 等于接管日常 Chrome 的会话——书签、登录态都现成，能直接访问
  已登录的 grok.com。如果 Chrome 已经在跑，先关掉再走这条命令启动。
"""

import json
import socket
import urllib.error
import urllib.parse
import urllib.request

import websockets
from websockets.sync.client import connect as ws_connect


class CDPError(Exception):
    """CDP 相关错误基类。"""


class CDPRefused(CDPError):
    """无法连接本地 Chrome（未启动或未开启 remote-debugging-port）。"""


class CDPNoTab(CDPError):
    """找不到符合条件的浏览器标签。"""


class CDPEvalError(CDPError):
    """注入的 JS 抛错或返回值结构异常。"""


_DEFAULT_HTTP_TIMEOUT = 5.0  # /json/list、/json/new 之类本地 HTTP


def _http_json(url, method="GET"):
    """一次简单的 HTTP 调用，响应必须为 JSON。失败抛 CDPRefused。"""
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=_DEFAULT_HTTP_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, socket.timeout, ConnectionRefusedError) as e:
        raise CDPRefused(f"无法连接本地 Chrome（{url}）：{e}") from e
    except OSError as e:
        raise CDPRefused(f"无法连接本地 Chrome（{url}）：{e}") from e
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise CDPError(f"Chrome 返回非 JSON（{url}）：{e}") from e


def _check_port(port):
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise ValueError(f"CDP port 非法: {port!r}")
    return port


def browser_is_up(port=9222):
    """轻探本地 Chrome 是否在指定端口监听（GET /json/version）。"""
    _check_port(port)
    try:
        _http_json(f"http://127.0.0.1:{port}/json/version")
        return True
    except CDPRefused:
        return False
    except CDPError:
        return True  # /json/version 偶尔会返回非标准 JSON，但能连上就算在


def list_targets(port=9222):
    """返回 /json/list 的原始对象列表。"""
    _check_port(port)
    data = _http_json(f"http://127.0.0.1:{port}/json/list")
    if not isinstance(data, list):
        raise CDPError("/json/list 返回结构异常")
    return data


def find_grok_tab_ws(port=9222):
    """在本地 Chrome 标签里找一个 grok.com 对话页（/c/<uuid>），返回 ws URL。

    没有匹配标签时抛 CDPNoTab。
    """
    for t in list_targets(port):
        if not isinstance(t, dict) or t.get("type") != "page":
            continue
        url = t.get("url") or ""
        # 仅匹配 grok.com 主机下的对话页；about:blank / 登录页不算
        if "grok.com" in url and "/c/" in url:
            ws = t.get("webSocketDebuggerUrl")
            if ws:
                return ws
    raise CDPNoTab(
        "未找到 grok.com 的对话标签。请先在 Chrome 中打开"
        " https://grok.com/c/<id> 后再执行 /import grok"
    )


def open_new_tab_ws(port, url):
    """让本地 Chrome 打开一个新标签到 url，返回其 ws URL。

    路径：
      1. 走 /json/version 拿到浏览器级 WebSocket URL
      2. 在浏览器 WS 上发 Target.createTarget {url}
      3. 在 /json/list 中按 targetId 找到新建标签，取它自己的 ws URL

    不再用 /json/new?url=：新版 Chrome 的 HTTP /json/new 不再接受
    ?url= 参数（直接返回 405 Method Not Allowed）。

    此接口会复用 Chrome 当前的用户配置（含已登录的 grok.com 会话）。
    """
    import time

    _check_port(port)

    try:
        version_info = _http_json(f"http://127.0.0.1:{port}/json/version")
    except CDPRefused:
        raise
    if not isinstance(version_info, dict):
        raise CDPError("/json/version 返回结构异常")
    browser_ws = version_info.get("webSocketDebuggerUrl")
    if not browser_ws:
        raise CDPError(
            f"/json/version 未返回 webSocketDebuggerUrl：{version_info!r}"
        )

    target_id = _browser_create_target(browser_ws, url, timeout=10.0)

    # 创建后 /json/list 里不一定立刻可见（targetId 注册有几十毫秒延迟），轮询一会儿。
    deadline = time.monotonic() + 5.0
    while True:
        try:
            targets = list_targets(port=port)
        except CDPRefused:
            raise
        for t in targets:
            if not isinstance(t, dict):
                continue
            if t.get("id") == target_id and t.get("type") == "page":
                ws = t.get("webSocketDebuggerUrl")
                if ws:
                    return ws
        if time.monotonic() >= deadline:
            raise CDPError(
                f"Target.createTarget 后未在 /json/list 中找到新建标签 "
                f"（targetId={target_id}）。Chrome 版本可能不兼容。"
            )
        time.sleep(0.1)


def _browser_create_target(browser_ws, url, timeout=10.0):
    """通过浏览器级 WebSocket 调用 Target.createTarget，返回新建 targetId。"""
    msg_id = 1
    with ws_connect(
        browser_ws,
        open_timeout=_DEFAULT_HTTP_TIMEOUT,
        close_timeout=1.0,
        max_size=4 * 1024 * 1024,
    ) as ws:
        ws.send(
            json.dumps(
                {
                    "id": msg_id,
                    "method": "Target.createTarget",
                    "params": {"url": url},
                }
            )
        )
        while True:
            raw = ws.recv(timeout=timeout)
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            try:
                resp = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if resp.get("id") != msg_id:
                continue
            if "error" in resp:
                raise CDPError(f"Target.createTarget 失败：{resp['error']}")
            result = resp.get("result") or {}
            target_id = result.get("targetId")
            if not target_id:
                raise CDPError(f"Target.createTarget 未返回 targetId：{resp!r}")
            return target_id


def _ws_call(ws_url, method, params, timeout):
    """一次 CDP JSON-RPC 调用，等待 id 匹配的响应。

    期间到达的事件帧（Page.loadEventFired 等）一律忽略。
    抛出：
      - CDPRefused：WebSocket 无法建立（Chrome 已关 / ws URL 已失效）
      - websockets.WebSocketException：底层网络错误
      - OSError / TimeoutError：超时时
    """
    msg_id = 1
    try:
        with ws_connect(
            ws_url,
            open_timeout=_DEFAULT_HTTP_TIMEOUT,
            close_timeout=1.0,
            max_size=8 * 1024 * 1024,
        ) as ws:
            ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
            while True:
                raw = ws.recv(timeout=timeout)
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                try:
                    resp = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if resp.get("id") == msg_id:
                    return resp
                # 非本调用的事件帧（method 字段、targetID/...），跳过
    except (OSError, TimeoutError, websockets.WebSocketException) as e:
        raise CDPRefused(f"WebSocket 通信失败（{ws_url}）：{e}") from e
    return {}


def evaluate_and_parse(ws_url, expression, timeout=10.0, await_promise=False):
    """Runtime.evaluate 注入 expression，并把返回值（应为 JSON 字符串）反序列化。

    await_promise: 若为 True，CDP 会等到 expression 返回的 Promise resolve 后再读结果。
                   grok.js 用它做"等页面渲染"的轮询重试。

    对刚创建的 target，第一次 Runtime.evaluate 偶尔会撞上
    -32000 "Cannot find default execution context"，会自动重试几次。

    页面 JS 抛错时抛 CDPEvalError（包含原始 description）。
    """
    import time

    last_err = None
    # 首次重试不延迟；之后每次翻倍，最大 0.8s。总重试窗口 ~2s。
    delays = [0.0, 0.1, 0.2, 0.4, 0.8]
    for delay in delays:
        if delay:
            time.sleep(delay)
        try:
            resp = _ws_call(
                ws_url,
                "Runtime.evaluate",
                {
                    "expression": expression,
                    "returnByValue": True,
                    "awaitPromise": await_promise,
                },
                timeout=timeout,
            )
        except CDPRefused:
            raise

        if not resp:
            last_err = CDPEvalError("CDP 未返回任何响应")
            continue

        if "error" in resp:
            err = resp["error"]
            code = (err or {}).get("code")
            msg = (err or {}).get("message", "")
            # 刚开的标签第一次 evaluate 很容易缺 execution context
            if code == -32000 and "execution context" in (msg or "").lower():
                last_err = CDPEvalError(f"CDP 调用错误：{err}")
                continue
            raise CDPEvalError(f"CDP 调用错误：{err}")

        result = resp.get("result") or {}
        if result.get("exceptionDetails"):
            details = result["exceptionDetails"]
            exc = details.get("exception") or {}
            text = exc.get("description") or details.get("text") or str(details)
            raise CDPEvalError(text)

        remote = result.get("result") or {}
        value = remote.get("value")
        if value is None:
            raise CDPEvalError("Runtime.evaluate 未返回有效值")

        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError as e:
                raise CDPEvalError(f"返回值不是合法 JSON：{e}") from e
        if isinstance(value, dict):
            return value

        raise CDPEvalError(f"Runtime.evaluate 返回值类型不支持：{type(value).__name__}")

    raise last_err or CDPEvalError("Runtime.evaluate 反复失败")
