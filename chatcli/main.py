import sys

from chatcli.cache import (
    apply_imported_messages,
    export_conversation,
    import_conversation,
    new_conversation,
    reset_screen_visual,
    resume_conversation,
    rewind_conversation,
    save_conversation,
)
from chatcli.config import (
    get_api_key,
    get_current_model_config,
    load_config,
    print_config,
    print_help,
)
from chatcli.models import switch_model
from chatcli.utils import StreamingBoldStripper, read_framed_input, strip_markdown_bold


def trim_history(messages, max_history_messages):
    """
    裁剪上下文消息数量。
    永远保留第一条 SystemMessage。
    max_history_messages 为 None 时不限制数量。
    """
    if not messages or max_history_messages is None:
        return messages

    system_message = messages[0]
    history = messages[1:]

    if len(history) > max_history_messages:
        history = history[-max_history_messages:]

    return [system_message] + history


def handle_import_grok(rest, config, state):
    """
    /import grok [url] 处理：
      - 无 url：抓当前打开的 grok.com 对话页
      - 有 url：让本地 Chrome 新开一个标签并跳过去，再抓

    CDP 未启时自动拉起本地 Chrome（独立 user-data-dir），不需要用户先手动起。
    任何 CDP 错误已经在 fetch_and_normalize / launch_chrome_cdp 里就地打印，这里只做结果分发。
    """
    from chatcli.cdp import (
        CDPError,
        ChromeNotFound,
        browser_is_up,
        find_chrome_executable,
        launch_chrome_cdp,
    )
    from chatcli.config import (
        get_cdp_port,
        get_cdp_user_data_dir,
        prompt_first_run_cdp_setup,
    )
    from chatcli.fetchers import grok as grok_fetcher

    parts = rest.split(maxsplit=1)
    url = parts[1].strip() if len(parts) > 1 else ""
    url = url or None

    # 端口未起 → 让 chatcli 自己拉起 Chrome
    if not browser_is_up(config.get("cdp_port", 9222)):
        user_data_dir = get_cdp_user_data_dir(config)
        if not user_data_dir:
            # 首次使用：让用户输入 profile 目录 + 端口，写入 config.json
            prompt_first_run_cdp_setup(config)
        # 读回（可能被 prompt 更新过 port）
        port = get_cdp_port(config)
        user_data_dir = get_cdp_user_data_dir(config)

        try:
            chrome_path = find_chrome_executable()
        except ChromeNotFound as e:
            print(f"错误: {e}")
            print(
                "  备选：在 ~/.chatcli/config.json 里加 'chrome_executable' "
                "指向本地 Chrome 绝对路径后重试。"
            )
            return

        print(f"启动 Chrome CDP 模式（port={port}，profile={user_data_dir}）...")
        try:
            launch_chrome_cdp(
                chrome_path=chrome_path,
                port=port,
                user_data_dir=user_data_dir,
            )
        except CDPError as e:
            print(f"错误: {e}")
            return
        print("Chrome CDP 已就绪。")
    else:
        port = config.get("cdp_port", 9222)

    msgs = grok_fetcher.fetch_and_normalize(port=port, url=url)
    if msgs is None:
        # fetcher 已经就地打印了错误
        return
    if not msgs:
        print("错误: 从 grok.com 抓回的内容为空，没法导入")
        return

    apply_imported_messages(msgs, config, state, source_label="grok")


def _import_llm_deps():
    """导入 LLM 相关依赖；缺失时给出安装提示。"""
    try:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI
    except ImportError as e:
        print("错误: 缺少运行所需的 Python 包。")
        print(f"详情: {e}")
        print("请在本环境中重新安装（会自动下载全部依赖）:")
        print("  pip install -e .")
        print("或在仓库根目录:")
        print("  pip install .")
        raise SystemExit(1) from e
    return AIMessage, HumanMessage, SystemMessage, ChatOpenAI


def run_chat():
    """聊天主循环：在当前控制台运行。"""
    AIMessage, HumanMessage, SystemMessage, ChatOpenAI = _import_llm_deps()

    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass
    sys.stdout.flush()

    # 清空当前控制台已有输出，从顶部重新开始
    reset_screen_visual()

    config = load_config()
    model_config = get_current_model_config(config)
    llm = ChatOpenAI(
        model=model_config["model"],
        api_key=get_api_key(config),
        base_url=model_config["base_url"],
        temperature=config.get("temperature", 0.7),
        streaming=config.get("stream", False)
    )

    llm_ref = {"llm": llm}

    system_prompt = model_config.get("system_prompt", "")
    max_history_messages = config.get("max_history_messages")

    state = {
        "system_prompt": system_prompt,
        "current_model": model_config["model"],
        "messages": [SystemMessage(content=system_prompt)],
        "current_conv": new_conversation(model_config["model"], system_prompt),
    }

    print("Console LLM Chat 已启动。输入 /help 查看命令。")

    # /rewind 预填框里若再输入命令，经此注入下一轮，避免被当成普通消息
    pending_input = None

    while True:
        try:
            if pending_input is not None:
                user_input = pending_input
                pending_input = None
            else:
                user_input = read_framed_input("You: ").strip()
            if not user_input:
                continue

            if user_input == "/help":
                print_help()
                continue

            if user_input == "/clear":
                model_config = get_current_model_config(config)
                state["system_prompt"] = model_config.get("system_prompt", "")
                state["messages"] = [SystemMessage(content=state["system_prompt"])]
                state["current_conv"] = new_conversation(
                    state["current_model"], state["system_prompt"]
                )
                reset_screen_visual()
                print("已清空上下文。")
                continue

            if user_input == "/config":
                print_config(config)
                continue

            if user_input == "/model":
                old_model = config["current_model"]
                new_model = switch_model(config, llm_ref)
                if new_model != old_model:
                    model_config = get_current_model_config(config)
                    state["current_model"] = model_config["model"]
                    state["system_prompt"] = model_config.get("system_prompt", "")
                    state["messages"] = [SystemMessage(content=state["system_prompt"])]
                    state["current_conv"] = new_conversation(
                        state["current_model"], state["system_prompt"]
                    )
                continue

            if user_input == "/resume":
                resume_conversation(config, llm_ref, state)
                continue

            if user_input == "/import" or user_input.startswith("/import "):
                rest = user_input[len("/import") :].strip()
                # /import grok [url] — 直接从打开/指定的 grok 对话页抓取
                if rest == "grok" or rest.startswith("grok "):
                    handle_import_grok(rest, config, state)
                    continue
                # 否则按文件路径走
                import_conversation(rest, config, state)
                continue

            if user_input == "/export" or user_input.startswith("/export "):
                path = user_input[len("/export") :].strip()
                export_conversation(path, state)
                continue

            if user_input == "/rewind":
                prefill = rewind_conversation(config, llm_ref, state)
                if prefill is None:
                    continue
                print(
                    "[Rewind] 直接回车发送；可改写内容；"
                    "再输入 /rewind 继续回退；/cancel 取消:"
                )
                edit = read_framed_input("You: ", initial=prefill or "").strip()
                if edit == "/cancel":
                    print("已取消。")
                    continue
                if not edit:
                    continue
                # 重新走命令分发（支持预填框内再次 /rewind 等命令）
                pending_input = edit
                continue

            if user_input == "/exit":
                print("再见!")
                break

            state["messages"].append(HumanMessage(content=user_input))
            state["current_conv"]["messages"].append({"role": "user", "content": user_input})
            save_conversation(state["current_conv"])

            if config.get("stream"):
                print("\nAI: ", end="", flush=True)
                response_content = ""
                stripper = StreamingBoldStripper()
                for chunk in llm_ref["llm"].stream(state["messages"]):
                    if not chunk.content:
                        continue
                    out_str = stripper.feed(chunk.content)
                    if out_str:
                        print(out_str, end="", flush=True)
                        response_content += out_str
                tail = stripper.flush()
                if tail:
                    print(tail, end="", flush=True)
                    response_content += tail
                print()
                response = AIMessage(content=response_content)
            else:
                response = llm_ref["llm"].invoke(state["messages"])
                content = strip_markdown_bold(response.content)
                print(f"\nAI: {content}")
                response = AIMessage(content=content)

            state["messages"].append(response)
            state["current_conv"]["messages"].append(
                {"role": "assistant", "content": response.content}
            )
            state["messages"] = trim_history(state["messages"], max_history_messages)
            save_conversation(state["current_conv"])

        except KeyboardInterrupt:
            print("\n\n再见!")
            break

        except EOFError:
            print("\n再见!")
            break

        except Exception as e:
            error_msg = str(e)

            if "model" in error_msg.lower() or "not found" in error_msg.lower():
                print("\n错误: 模型不可用")
                print("请检查 ~/.chatcli/config.json 中的 model 配置是否正确")
            elif (
                "api" in error_msg.lower()
                or "key" in error_msg.lower()
                or "auth" in error_msg.lower()
                or "unauthorized" in error_msg.lower()
            ):
                print("\n错误: API 认证失败")
                print(
                    "请检查 ~/.chatcli/config.json 的 api_key："
                    "可为环境变量名，或直接填写密钥"
                )
            else:
                print("\n错误: 无法连接到 API")
                print(f"错误信息: {error_msg}")


def main(argv=None):
    """控制台入口：chatcli / python -m chatcli（始终在当前终端运行）"""
    run_chat()


if __name__ == "__main__":
    main()