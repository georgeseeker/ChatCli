"""Chrome DevTools Protocol 客户端：通过本地 Chrome 远程调试拉取数据。

设计目标：
  - 仅依赖 stdlib + websockets（已在依赖里），便于跨平台打包
  - 只暴露 fetcher 真正用到的高层 API：找标签 / 开标签 / 注入 JS
  - 提供 launch_chrome_cdp() 让调用方在 CDP 未启时拉起本地 Chrome
    （用专用的 user-data-dir，不复用日常 Chrome 配置——现代 Chrome
    已禁止调试进程直接占用本机默认 profile）
  - 异常类型明确（CDPError / CDPRefused / CDPNoTab / CDPEvalError），
    上层（fetchers/grok.py + main.py）按类区分处理

自动启动：
  通常 /import grok 由 chatcli 自动拉起 Chrome（详见
  chatcli.main.handle_import_grok）。想手工启动一个调试实例时仍可用：
    Chrome.exe --remote-debugging-port=9222 --user-data-dir=<profile 目录>

  user-data-dir 必须是独立目录（不同于日常 Chrome 的默认配置），
  并在 ~/.chatcli/config.json 的 cdp_user_data_dir 字段里登记。
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
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


class ChromeNotFound(CDPError):
    """在系统里找不到 Chrome 可执行文件。"""


_DEFAULT_HTTP_TIMEOUT = 5.0  # /json/list、/json/new 之类本地 HTTP
_LAUNCH_WAIT_TIMEOUT = 10.0  # launch_chrome_cdp 默认等待 CDP 就绪秒数


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


# ---------------------------------------------------------------------------
# 自动启动 Chrome：让 /import grok 不用让用户先手动起 Chrome
# ---------------------------------------------------------------------------

_LAUNCH_POLL_INTERVAL = 0.2  # wait_for_cdp 轮询间隔


def find_chrome_executable():
    r"""返回 Chrome 可执行文件绝对路径；找不到抛 ChromeNotFound。

    查找顺序：
      Windows: 注册表 HKLM\...\Chrome.exe → Program Files / Program Files (x86) →
                shutil.which("chrome") 兜底
      macOS:   /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
      Linux:   which("google-chrome") → which("google-chrome-stable") →
                which("chromium") → which("chromium-browser")
    """
    candidates = []

    if sys.platform == "win32":
        # 1. 注册表：Chrome 安装时通常写到这里
        try:
            import winreg  # 仅 Windows 可用

            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for sub in (
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Google Chrome",
                    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Google Chrome",
                ):
                    try:
                        with winreg.OpenKey(hive, sub) as key:
                            value, _ = winreg.QueryValueEx(key, "InstallLocation")
                            if value:
                                exe = os.path.join(value, "chrome.exe")
                                if os.path.isfile(exe):
                                    candidates.append(exe)
                    except OSError:
                        continue
        except ImportError:
            pass

        # 2. 常见安装路径
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pfx86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        for base in (pf, pfx86):
            candidates.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))

        # 3. PATH 兜底
        on_path = shutil.which("chrome") or shutil.which("chrome.exe")
        if on_path:
            candidates.append(on_path)

    elif sys.platform == "darwin":
        candidates.extend(
            [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            ]
        )
        on_path = shutil.which("google-chrome") or shutil.which("Google Chrome")
        if on_path:
            candidates.append(on_path)

    else:  # linux / 其他 unix
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            on_path = shutil.which(name)
            if on_path:
                candidates.append(on_path)

    # 去重保序
    seen = set()
    for c in candidates:
        if c and os.path.isfile(c) and c not in seen:
            seen.add(c)
            return c

    raise ChromeNotFound(
        "找不到 Chrome 可执行文件。请先安装 Google Chrome，或在 ~/.chatcli/config.json 里"
        " 配置 chrome_executable 指向它的绝对路径。"
    )


def launch_chrome_cdp(
    chrome_path,
    port,
    user_data_dir,
    extra_args=None,
    wait_timeout=10.0,
):
    """后台启动 Chrome 到 CDP 调试模式，等待端口就绪后返回。

    参数：
      chrome_path:    Chrome 可执行文件绝对路径（先调 find_chrome_executable）
      port:           --remote-debugging-port 值
      user_data_dir:  --user-data-dir 值（必须是独立目录；不存在会自动创建）
      extra_args:     传给 Chrome 的额外命令行参数（list[str]，可选）
      wait_timeout:   等待 CDP 就绪的最长秒数

    进程行为：detached —— chatcli 退出后 Chrome 继续跑，下次 /import grok
    复用同一个调试实例（也复用 profile 里的登录态）。

    抛出：
      ChromeNotFound: chrome_path 不存在
      OSError:        创建 user_data_dir 失败 / 启动 Chrome 失败
      CDPError:       等待超时 Chrome 仍未监听 port
    """
    if not chrome_path or not os.path.isfile(chrome_path):
        raise ChromeNotFound(f"Chrome 可执行文件不存在: {chrome_path!r}")

    user_data_dir = os.path.abspath(user_data_dir)
    os.makedirs(user_data_dir, exist_ok=True)

    args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",  # 抑制首次启动欢迎页
        "--no-default-browser-check",
    ]
    if extra_args:
        args.extend(extra_args)

    # detach：Windows 用 DETACHED_PROCESS；POSIX 用 start_new_session=True
    popen_kwargs = {
        "args": args,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        CREATE_NO_WINDOW = 0x08000000
        popen_kwargs["creationflags"] = (
            DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        )
    else:
        popen_kwargs["start_new_session"] = True

    try:
        subprocess.Popen(**popen_kwargs)
    except OSError as e:
        raise ChromeNotFound(f"无法启动 Chrome（{chrome_path}）：{e}") from e

    # 等 CDP 端口就绪
    deadline = time.monotonic() + wait_timeout
    while time.monotonic() < deadline:
        if browser_is_up(port):
            return
        time.sleep(_LAUNCH_POLL_INTERVAL)

    raise CDPError(
        f"已启动 Chrome 但 {wait_timeout:.0f}s 内 {port} 端口未就绪。"
        " 请检查 Chrome 是否被安全软件拦截，或调大 wait_timeout。"
    )
