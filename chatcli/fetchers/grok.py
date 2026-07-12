"""Grok 对话 fetcher：通过 CDP 抓取 grok.com 当前对话并投影为 ChatCli 消息格式。

对外暴露两个函数：
  - fetch_grok_conversation(port=None, url=None) -> dict   纯操作，抛异常
  - fetch_and_normalize(port=None, url=None) -> list | None  分发器友好版

参数：
  port: 本地 Chrome 的远程调试端口，默认 9222（沿用 config.cdp_port）
  url:  可选；提供时会让 Chrome 打开新标签并跳转到该地址，再在那个标签里
        抽取对话。grok.com 需要登录态，必须复用本机 Chrome 的用户配置。
"""

from importlib import resources

from chatcli import cdp
from chatcli.cdp import CDPError


_JS_PACKAGE = "chatcli.fetchers"
_JS_NAME = "grok.js"


def _load_js_source() -> str:
    """从包内资源读取 grok.js 源码。

    使用 stdlib importlib.resources（Python 3.9+），在 editable install
    和 wheel install 下都能工作，前提是 pyproject.toml 里把 fetchers/*.js
    写进 package-data。
    """
    return (
        resources.files(_JS_PACKAGE)
        .joinpath(_JS_NAME)
        .read_text(encoding="utf-8")
    )


def fetch_grok_conversation(port=None, url=None) -> dict:
    """连接本地 Chrome，注入 grok.js，返回 Grok 原始导出格式的 dict。

    url:  None 时使用当前已打开的 grok 对话标签；
          字符串时让 Chrome 新开一个标签并跳过去（grok.js 会自等待加载）。

    Raises:
        chatcli.cdp.CDPError 及子类（CDPRefused / CDPNoTab / CDPEvalError）
    """
    if url:
        ws_url = cdp.open_new_tab_ws(port=port, url=url)
    else:
        ws_url = cdp.find_grok_tab_ws(port=port)
    expression = _load_js_source()
    # awaitPromise=True 让 grok.js 的 polling/wait 真正生效（CDP 会等到 Promise resolve）
    # 开新标签 + 等渲染 + 等消息一起算，单次允许更长时间
    return cdp.evaluate_and_parse(
        ws_url,
        expression,
        timeout=30.0,
        await_promise=True,
    )


def fetch_and_normalize(port=None, url=None):
    """fetch_grok_conversation 的分发器友好版。

    返回 ChatCli 期望的 [{role, content}, ...]（role 为 user/assistant）。
    失败时打印中文错误并返回 None。
    """
    try:
        payload = fetch_grok_conversation(port=port, url=url)
    except CDPError as e:
        print(f"错误: {e}")
        return None
    except Exception as e:
        print(f"错误: 从 grok.com 抓取失败: {e}")
        return None

    result = []
    for m in payload.get("messages") or []:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role == "human":
            role = "user"
        elif role == "ai":
            role = "assistant"
        else:
            # 未知 role 跳过，避免污染上下文
            continue
        if not content:
            continue
        result.append({"role": role, "content": content})
    return result