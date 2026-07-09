import json
import os
import secrets
import sys
from datetime import datetime

from config import get_current_model_config, save_config
from utils import READLINE_AVAILABLE

if sys.platform == "win32":
    import msvcrt


CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".cache")


def ensure_cache_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _conv_file_path(conv_id):
    return os.path.join(CACHE_DIR, f"{conv_id}.json")


def new_conversation(model, system_prompt):
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
    ensure_cache_dir()
    conv["updated_at"] = _now_iso()
    with open(_conv_file_path(conv["id"]), "w", encoding="utf-8") as f:
        json.dump(conv, f, ensure_ascii=False, indent=2)


def delete_conversation(conv_id):
    path = _conv_file_path(conv_id)
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def load_conversation_file(conv_id):
    path = _conv_file_path(conv_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_conversations():
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
    for path in empty_files:
        try:
            os.remove(path)
        except OSError:
            pass
    return items


def _format_conv_summary(conv):
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


def reset_screen_visual():
    """清屏 + 光标回顶部，模拟重启视觉效果（/clear 与 /resume 共用）"""
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def resume_conversation(config, llm_ref, state):
    """
    /resume 命令：选择并加载历史会话。
    成功加载返回 (True, new_model)；失败或取消返回 (False, current_model)。
    state 是 dict，承载 messages / system_prompt / current_conv 等可变状态。
    """
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    from utils import strip_markdown_bold
    conversations = list_conversations()
    if not conversations:
        print("暂无历史对话。")
        return False, config["current_model"]

    n = len(conversations)
    idx = 0

    print("\n历史对话:")
    print("提示: ↑↓ 选择  Enter 确认  d 删除")

    for i, conv in enumerate(conversations):
        prefix = "  >" if i == idx else "   "
        print(f"\033[2K{prefix} {_format_conv_summary(conv)}")
    sys.stdout.flush()

    sys.stdout.write(f"\033[{n}A")
    sys.stdout.write("\r")
    sys.stdout.flush()

    def rerender(new_idx):
        nonlocal idx
        if idx > 0:
            sys.stdout.write(f"\033[{idx}A")
        sys.stdout.write("\r")
        for i in range(n):
            if i > 0:
                sys.stdout.write("\n")
            prefix = "  >" if i == new_idx else "   "
            sys.stdout.write(f"\033[2K{prefix} {_format_conv_summary(conversations[i])}")
        sys.stdout.flush()
        back = n - 1 - new_idx
        if back > 0:
            sys.stdout.write(f"\033[{back}A")
        sys.stdout.write("\r")
        sys.stdout.flush()
        idx = new_idx

    if not READLINE_AVAILABLE:
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
            elif key == b'd' or key == b'D':
                conv_id = conversations[idx]["id"]
                if not delete_conversation(conv_id):
                    rest = n - 1 - idx
                    if rest > 0:
                        sys.stdout.write(f"\033[{rest}B")
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    print(f"删除失败: {conv_id}")
                    return False, config["current_model"]
                new_list = list_conversations()
                new_n = len(new_list)
                if new_n == 0:
                    rest = n - 1 - idx
                    if rest > 0:
                        sys.stdout.write(f"\033[{rest}B")
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    print(f"已删除会话 [{conv_id}]。暂无历史对话。")
                    return False, config["current_model"]
                if idx >= new_n:
                    idx = new_n - 1
                rest = n - 1 - idx
                if rest > 0:
                    sys.stdout.write(f"\033[{rest}B")
                sys.stdout.write("\n")
                sys.stdout.flush()
                conversations.clear()
                conversations.extend(new_list)
                n = new_n
                for i, conv in enumerate(conversations):
                    prefix = "  >" if i == idx else "   "
                    print(f"\033[2K{prefix} {_format_conv_summary(conv)}")
                sys.stdout.flush()
                if idx > 0:
                    sys.stdout.write(f"\033[{n - 1 - idx}A")
                sys.stdout.write("\r")
                sys.stdout.flush()

    chosen = conversations[idx]
    history_model = chosen.get("model")

    available_models = {
        cfg.get("model") for cfg in config["models"].values() if cfg.get("model")
    }
    if history_model not in available_models:
        print(f"错误: 历史模型 {history_model} 已不可用，无法恢复")
        return False, config["current_model"]

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

    # 切换前先持久化当前会话（非空时），保证它进入历史记录
    current_conv = state.get("current_conv")
    if current_conv and current_conv.get("messages"):
        save_conversation(current_conv)

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

    reset_screen_visual()

    print(f"已恢复会话 [{chosen['id']}]，模型: {history_model}，消息数: {len(messages) - 1}")

    restored_messages = chosen.get("messages", [])
    if restored_messages:
        print("\n--- 历史对话内容 ---")
        for m in restored_messages:
            role = m.get("role")
            content = m.get("content", "")
            if role == "user":
                print(f"\nYou: {content}")
            elif role == "assistant":
                print(f"\nAI: {strip_markdown_bold(content)}")
        print()
    return True, history_model
