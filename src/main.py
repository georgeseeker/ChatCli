import json
import os
import secrets
import subprocess
import sys
from datetime import datetime

try:
    import readline
    READLINE_AVAILABLE = True
except ImportError:
    READLINE_AVAILABLE = False

if sys.platform == "win32":
    import msvcrt


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(os.path.dirname(BASE_DIR), ".cache")


def load_config():
    """加载并校验配置文件"""
    config_path = os.path.join(BASE_DIR, "config.json")

    if not os.path.exists(config_path):
        print(f"错误: 配置文件 {config_path} 不存在")
        exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # api_key 从 config.json 中指定的环境变量读取
    api_key_env = config.get("api_key_env")
    if not api_key_env:
        print("错误: config.json 中未配置 api_key_env 字段")
        print("提示: 添加 \"api_key_env\": \"YOUR_API_KEY\" 来指定环境变量名")
        exit(1)

    api_key = os.environ.get(api_key_env)
    if not api_key:
        print(f"错误: 未设置环境变量 {api_key_env}")
        print(f"提示: 设置方法: $env:{api_key_env}=\"your-api-key\"")
        exit(1)
    config["api_key"] = api_key

    # 校验 models
    if "models" not in config or not config["models"]:
        print("错误: config.json 中未配置 models 字段")
        exit(1)

    # 校验 current_model 匹配某个配置的 model 字段
    current = config.get("current_model")
    if not current:
        print("错误: config.json 中未配置 current_model 字段")
        exit(1)

    # 验证 current_model 确实对应某个配置
    model_found = False
    for model_config in config["models"].values():
        if model_config.get("model") == current:
            model_found = True
            break

    if not model_found:
        print(f"错误: current_model '{current}' 在 models 中未找到对应配置")
        exit(1)

    return config


def save_config(config):
    """保存配置到文件"""
    config_path = os.path.join(BASE_DIR, "config.json")
    config_to_save = {k: v for k, v in config.items() if k != "api_key"}
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_to_save, f, indent=2, ensure_ascii=False)


def ensure_cache_dir():
    """确保 .cache 目录存在"""
    os.makedirs(CACHE_DIR, exist_ok=True)


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _conv_file_path(conv_id):
    return os.path.join(CACHE_DIR, f"{conv_id}.json")


def new_conversation(model, system_prompt):
    """创建新会话并落盘，返回 conversation dict"""
    ensure_cache_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_id = secrets.token_hex(3)
    conv_id = f"{timestamp}_{short_id}"
    now = _now_iso()
    conv = {
        "id": conv_id,
        "created_at": now,
        "updated_at": now,
        "model": model,
        "system_prompt": system_prompt,
        "messages": [],
    }
    save_conversation(conv)
    return conv


def save_conversation(conv):
    """把 conversation 写回磁盘"""
    ensure_cache_dir()
    conv["updated_at"] = _now_iso()
    with open(_conv_file_path(conv["id"]), "w", encoding="utf-8") as f:
        json.dump(conv, f, ensure_ascii=False, indent=2)


def load_conversation_file(conv_id):
    """按 id 读取会话文件"""
    path = _conv_file_path(conv_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_conversations():
    """扫描 .cache 下所有非空会话，按 updated_at 倒序返回"""
    ensure_cache_dir()
    items = []
    empty_files = []
    for name in os.listdir(CACHE_DIR):
        if not name.endswith(".json"):
            continue
        path = os.path.join(CACHE_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                conv = json.load(f)
            if conv.get("messages"):
                items.append(conv)
            else:
                empty_files.append(path)
        except (OSError, json.JSONDecodeError):
            continue
    items.sort(key=lambda c: c.get("updated_at", ""), reverse=True)
    # 清理空会话文件（跳过当前活跃会话对应的文件）
    for path in empty_files:
        try:
            os.remove(path)
        except OSError:
            pass
    return items


def get_current_model_config(config):
    """获取当前模型的配置"""
    current = config["current_model"]
    for model_config in config["models"].values():
        if model_config.get("model") == current:
            return model_config
    return None


def print_help():
    """打印帮助信息"""
    print("""
可用命令:
  /help    - 显示此帮助信息
  /clear   - 清空上下文，保留 system prompt
  /config  - 显示当前配置
  /model   - 切换模型
  /resume  - 恢复历史对话
  /exit    - 退出聊天窗口
""")


def print_config(config):
    """打印当前配置"""
    current = config["current_model"]
    models = config["models"]

    # 获取所有可用的模型真实名称
    available = [m.get("model") for m in models.values()]

    print(f"""
当前模型: {current}
可用模型: {', '.join(available)}

模型配置:
  temperature: {config.get("temperature", 0.7)}
  stream: {config.get("stream", False)}
  api_key_env: {config.get("api_key_env", "")}
""")


def get_model_list(config):
    """获取模型名称列表"""
    model_list = []
    for model_config in config["models"].values():
        model_name = model_config.get("model")
        if model_name:
            model_list.append(model_config)
    return model_list


def print_models(config):
    """打印可用模型列表"""
    models = config["models"]
    current = config["current_model"]

    print("\n可用模型:")
    model_list = get_model_list(config)

    for i, cfg in enumerate(model_list, 1):
        name = cfg.get("model")
        marker = " [当前]" if name == current else ""
        print(f"  {i}. {name}{marker}")
    print()


def switch_model(config, llm_ref):
    """
    切换模型
    llm_ref: 包含 llm 的可变引用，用于更新
    """
    current = config["current_model"]
    model_list = get_model_list(config)

    if not model_list:
        print("没有可用模型")
        return current

    print("\n可用模型:")

    def print_selection(idx):
        """打印选中状态"""
        for i, cfg in enumerate(model_list):
            name = cfg.get("model")
            marker = ""
            if name == current:
                marker = " [当前]"
            prefix = "  >" if i == idx else "   "
            print(f"\033[K{prefix} {name}{marker}")
        # 光标上移回到起始位置
        print(f"\033[{len(model_list)}A", end="")

    if not READLINE_AVAILABLE:
        # 回退到简单输入
        for i, cfg in enumerate(model_list, 1):
            name = cfg.get("model")
            marker = " [当前]" if name == current else ""
            print(f"  {i}. {name}{marker}")
        print()
        try:
            choice = input("选择模型编号 (直接回车取消): ").strip()
            if not choice:
                print("已取消。")
                return current
            idx = int(choice) - 1
            if idx < 0 or idx >= len(model_list):
                print("无效的选择。")
                return current
        except ValueError:
            print("请输入有效编号。")
            return current
    else:
        # 使用 msvcrt 上下键选择 (Windows)
        idx = 0
        print_selection(idx)

        while True:
            key = msvcrt.getch()

            if key == b'\xe0':  # 方向键前缀
                key = msvcrt.getch()
                if key == b'H':  # 上
                    idx = (idx - 1) % len(model_list)
                    print_selection(idx)
                elif key == b'P':  # 下
                    idx = (idx + 1) % len(model_list)
                    print_selection(idx)
            elif key == b'\r' or key == b'\n':  # 回车
                print()  # 换行
                break
            elif key == b'\x03':  # Ctrl+C
                print("\n已取消。")
                return current

    new_model = model_list[idx].get("model")
    if new_model == current:
        print("当前已是该模型。")
        return current

    config["current_model"] = new_model
    save_config(config)

    # 重新创建 llm
    from langchain_openai import ChatOpenAI
    model_config = get_current_model_config(config)
    new_llm = ChatOpenAI(
        model=model_config["model"],
        api_key=config["api_key"],
        base_url=model_config["base_url"],
        temperature=config.get("temperature", 0.7),
        streaming=config.get("stream", False)
    )
    llm_ref["llm"] = new_llm

    print(f"已切换到模型: {new_model}")
    return new_model


def _format_conv_summary(conv):
    """生成单行会话摘要：时间 + 首条 user + 模型名"""
    updated = conv.get("updated_at", "")
    msgs = conv.get("messages", [])
    first_user = ""
    for m in msgs:
        if m.get("role") == "user":
            first_user = (m.get("content") or "").strip().replace("\n", " ")
            break
    if len(first_user) > 40:
        first_user = first_user[:40] + "…"
    model = conv.get("model", "")
    if first_user:
        return f"{updated}  {model}  {first_user}"
    return f"{updated}  {model}  (空)"


def resume_conversation(config, llm_ref, state):
    """
    /resume 命令：选择并加载历史会话。
    成功加载返回 (True, new_model)；失败或取消返回 (False, current_model)。
    state 是 dict，承载 messages / system_prompt / current_conv 等可变状态。
    """
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    conversations = list_conversations()
    if not conversations:
        print("暂无历史对话。")
        return False, config["current_model"]

    n = len(conversations)

    print("\n历史对话:")

    # 首次打印整张列表
    for i, conv in enumerate(conversations):
        prefix = "  >" if i == 0 else "   "
        print(f"\033[2K{prefix} {_format_conv_summary(conv)}")
    sys.stdout.flush()

    # 光标上移回到列表第一行（用相对移动，不依赖绝对行号）
    if n > 0:
        sys.stdout.write(f"\033[{n}A")
        sys.stdout.flush()

    idx = 0

    def rerender(new_idx):
        """从当前光标行往上回到列表顶部，全部重绘，再回到目标行"""
        nonlocal idx
        current = idx
        # 从当前行回到第一行
        if current > 0:
            sys.stdout.write(f"\033[{current}A")
        # 重绘所有行
        for i in range(n):
            if i > 0:
                sys.stdout.write("\n")
            prefix = "  >" if i == new_idx else "   "
            sys.stdout.write(f"\033[2K{prefix} {_format_conv_summary(conversations[i])}")
        # 光标回到目标行
        back = n - 1 - new_idx
        if back > 0:
            sys.stdout.write(f"\033[{back}A")
        sys.stdout.flush()
        idx = new_idx

    if not READLINE_AVAILABLE:
        # 回到列表末尾后，以编号形式展示
        sys.stdout.write(f"\033[{n - idx}B\n")
        sys.stdout.flush()
        for i, conv in enumerate(conversations, 1):
            print(f"  {i}. {_format_conv_summary(conv)}")
        print()
        try:
            choice = input("选择编号 (直接回车取消): ").strip()
            if not choice:
                print("已取消。")
                return False, config["current_model"]
            idx = int(choice) - 1
            if idx < 0 or idx >= n:
                print("无效的选择。")
                return False, config["current_model"]
        except ValueError:
            print("请输入有效编号。")
            return False, config["current_model"]
    else:
        while True:
            key = msvcrt.getch()
            if key == b'\xe0':
                key = msvcrt.getch()
                if key == b'H':
                    rerender((idx - 1) % n)
                elif key == b'P':
                    rerender((idx + 1) % n)
            elif key == b'\r' or key == b'\n':
                # 光标移到列表末尾
                rest = n - 1 - idx
                if rest > 0:
                    sys.stdout.write(f"\033[{rest}B")
                sys.stdout.write("\n")
                sys.stdout.flush()
                break
            elif key == b'\x03':
                rest = n - 1 - idx
                if rest > 0:
                    sys.stdout.write(f"\033[{rest}B")
                sys.stdout.write("\n")
                sys.stdout.flush()
                print("已取消。")
                return False, config["current_model"]

    chosen = conversations[idx]
    history_model = chosen.get("model")

    available_models = {
        cfg.get("model") for cfg in config["models"].values() if cfg.get("model")
    }
    if history_model not in available_models:
        print(f"错误: 历史模型 {history_model} 已不可用，无法恢复")
        return False, config["current_model"]

    # 切换模型
    config["current_model"] = history_model
    save_config(config)
    model_config = get_current_model_config(config)
    llm_ref["llm"] = ChatOpenAI(
        model=model_config["model"],
        api_key=config["api_key"],
        base_url=model_config["base_url"],
        temperature=config.get("temperature", 0.7),
        streaming=config.get("stream", False),
    )

    # 恢复 messages
    messages = [SystemMessage(content=chosen.get("system_prompt", ""))]
    for m in chosen.get("messages", []):
        role = m.get("role")
        content = m.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))

    state["messages"] = messages
    state["system_prompt"] = chosen.get("system_prompt", "")
    state["current_conv"] = chosen

    print(f"已恢复会话 [{chosen['id']}]，模型: {history_model}，消息数: {len(messages) - 1}")
    return True, history_model


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


def run_chat():
    """聊天主循环：只在子窗口运行"""
    from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
    from langchain_openai import ChatOpenAI
    from utils import strip_markdown_bold

    # 子进程的 stdout 在新控制台里可能被 block-buffered，
    # 导致 ANSI 转义序列堆积后一次性输出，破坏上下键交互。
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, OSError):
        pass
    sys.stdout.flush()

    config = load_config()
    model_config = get_current_model_config(config)
    llm = ChatOpenAI(
        model=model_config["model"],
        api_key=config["api_key"],
        base_url=model_config["base_url"],
        temperature=config.get("temperature", 0.7),
        streaming=config.get("stream", False)
    )

    # 用于在模型切换时更新 llm
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

    while True:
        try:
            user_input = input("\nYou: ").strip()

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

            if user_input == "/exit":
                print("再见!")
                break

            state["messages"].append(HumanMessage(content=user_input))
            state["current_conv"]["messages"].append({"role": "user", "content": user_input})
            save_conversation(state["current_conv"])

            if config.get("stream"):
                # 流式输出
                print("\nAI: ", end="", flush=True)
                response_content = ""
                for chunk in llm_ref["llm"].stream(state["messages"]):
                    if chunk.content:
                        content = strip_markdown_bold(chunk.content)
                        print(content, end="", flush=True)
                        response_content += content
                print()
                response = AIMessage(content=response_content)
            else:
                response = llm_ref["llm"].invoke(state["messages"])
                content = strip_markdown_bold(response.content)
                print(f"\nAI: {content}")

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
                print("请检查 config.json 中的 model 配置是否正确")
            elif (
                "api" in error_msg.lower()
                or "key" in error_msg.lower()
                or "auth" in error_msg.lower()
                or "unauthorized" in error_msg.lower()
            ):
                print("\n错误: API 认证失败")
                print(f"请检查环境变量 {config.get('api_key_env', 'api_key_env')} 是否正确")
            else:
                print("\n错误: 无法连接到 API")
                print(f"错误信息: {error_msg}")


def launch_chat_window():
    """
    启动新的聊天窗口。
    父进程只负责创建子窗口，创建后立即退出。
    """
    script_path = os.path.abspath(__file__)

    subprocess.Popen(
        [sys.executable, script_path, "--child"],
        cwd=BASE_DIR,
        creationflags=subprocess.CREATE_NEW_CONSOLE
    )


def main():
    is_child = len(sys.argv) > 1 and sys.argv[1] == "--child"

    if is_child:
        run_chat()
        return

    launch_chat_window()


if __name__ == "__main__":
    main()
