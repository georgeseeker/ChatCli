import json
import os
import secrets
import sys
from datetime import datetime

from chatcli.config import (
    CACHE_DIR,
    ensure_chatcli_home,
    get_api_key,
    get_current_model_config,
    save_config,
)
from chatcli.utils import print_user_block, strip_markdown_bold

if sys.platform == "win32":
    import msvcrt


def ensure_cache_dir():
    ensure_chatcli_home()


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _conv_file_path(conv_id):
    return str(CACHE_DIR / f"{conv_id}.json")


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
    try:
        names = os.listdir(CACHE_DIR)
    except OSError:
        return []
    for name in names:
        if not name.endswith(".json"):
            continue
        path = str(CACHE_DIR / name)
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
            first_user = strip_markdown_bold((m.get("content") or "").strip()).replace("\n", " ")
            break
    if len(first_user) > 40:
        first_user = first_user[:40] + "…"
    model = conv.get("model", "")
    if first_user:
        return f"{updated}  {model}  {first_user}"
    return f"{updated}  {model}  (空)"


def reset_screen_visual():
    """清屏 + 光标回顶部（启动、/clear、/resume 等共用）。"""
    if sys.platform == "win32":
        # cmd / PowerShell 下 cls 最可靠，可清掉本窗口先前输出
        os.system("cls")
    else:
        # 2J 清屏，3J 尽量清滚动缓冲，H 光标回左上
        sys.stdout.write("\033[2J\033[3J\033[H")
        sys.stdout.flush()


def _interactive_picker(items, header, hint, on_delete=None, start_index=0):
    """
    交互式列表选择器：↑↓ 移动  Enter 确认  Ctrl-C 取消  d 删除（可选）。
    items: 已格式化好的字符串列表（每项一行）。
    start_index: 初始光标位置（默认 0，方便 /rewind 传 n-1 让光标停在最新条目）。
    on_delete(idx): 可选删除回调，应返回 (new_items, action)：
        - action == 'continue': 列表更新为 new_items，选择器继续
        - action == 'empty' 或返回 None 表示列表已空/失败，终止
    返回 (selected_idx, 'selected') 或 (None, 'cancelled') 或 (None, 'empty')。
    """
    n = len(items)
    if n == 0:
        return None, "empty"

    idx = max(0, min(start_index, n - 1))
    use_interactive = sys.platform == "win32"

    if not use_interactive:
        print(f"\n{header}")
        if hint:
            print(hint)
        for i, item in enumerate(items, 1):
            print(f"  {i}. {item}")
        print()
        try:
            choice = input("选择编号 (直接回车取消): ").strip()
            if not choice:
                print("已取消。")
                return None, "cancelled"
            idx = int(choice) - 1
            if idx < 0 or idx >= n:
                print("无效的选择。")
                return None, "cancelled"
        except ValueError:
            print("请输入有效编号。")
            return None, "cancelled"
        return idx, "selected"

    print(f"\n{header}")
    if hint:
        print(hint)

    # 用 write 绘制列表（最后一项不额外换行），与 rerender 光标约定一致：
    # 绘制结束后光标停在最后一项所在行，再上移 (n-1-idx) 行到高亮项。
    # 若用 print，光标会多落在列表下方空行，上移少一行，导致后续重绘时
    # 第 0 行残留（/rewind 默认停在末项时，按 ↑ 会出现 #1 双份）。
    for i, item in enumerate(items):
        if i > 0:
            sys.stdout.write("\n")
        prefix = "  >" if i == idx else "   "
        sys.stdout.write(f"\033[2K{prefix} {item}")
    sys.stdout.flush()

    # 光标回到高亮那一行（而非首行），使初始视觉与 start_index 一致
    back = n - 1 - idx
    if back > 0:
        sys.stdout.write(f"\033[{back}A")
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
            sys.stdout.write(f"\033[2K{prefix} {items[i]}")
        sys.stdout.flush()
        sys.stdout.write("\033[J")
        sys.stdout.flush()
        back = n - 1 - new_idx
        if back > 0:
            sys.stdout.write(f"\033[{back}A")
        sys.stdout.write("\r")
        sys.stdout.flush()
        idx = new_idx

    def bail_with_message(msg):
        rest = n - 1 - idx
        if rest > 0:
            sys.stdout.write(f"\033[{rest}B")
        sys.stdout.write("\n")
        sys.stdout.flush()
        print(msg)

    while True:
        key = msvcrt.getch()
        if key == b"\xe0":
            key = msvcrt.getch()
            if key == b"H":
                rerender((idx - 1) % n)
            elif key == b"P":
                rerender((idx + 1) % n)
        elif key == b"\r" or key == b"\n":
            rest = n - 1 - idx
            if rest > 0:
                sys.stdout.write(f"\033[{rest}B")
            sys.stdout.write("\n")
            sys.stdout.flush()
            return idx, "selected"
        elif key == b"\x03":
            bail_with_message("已取消。")
            return None, "cancelled"
        elif on_delete is not None and (key == b"d" or key == b"D"):
            old_idx = idx
            result = on_delete(idx)
            if not result:
                bail_with_message("删除失败。")
                return None, "cancelled"
            new_items, action = result
            if action == "empty" or not new_items:
                bail_with_message("列表已清空。")
                return None, "empty"
            items.clear()
            items.extend(new_items)
            n = len(items)
            if idx >= n:
                idx = n - 1
            rewrite_count = n - old_idx
            if rewrite_count > 0:
                for i in range(rewrite_count):
                    write_i = old_idx + i
                    prefix = "  >" if write_i == idx else "   "
                    sys.stdout.write(f"\033[2K{prefix} {items[write_i]}")
                    if i < rewrite_count - 1:
                        sys.stdout.write("\n")
                sys.stdout.write("\033[J")
                back = n - 1 - idx
                if back > 0:
                    sys.stdout.write(f"\033[{back}A")
            else:
                sys.stdout.write("\033[2K")
                move_up = old_idx - idx
                if move_up > 0:
                    sys.stdout.write(f"\033[{move_up}A")
                sys.stdout.write("\r")
                sys.stdout.write(f"\033[2K  > {items[idx]}")
            sys.stdout.write("\r")
            sys.stdout.flush()

    return None, "cancelled"  # unreachable


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

    items = [_format_conv_summary(c) for c in conversations]

    def on_delete(idx):
        conv_id = conversations[idx]["id"]
        if not delete_conversation(conv_id):
            return None
        new_list = list_conversations()
        if not new_list:
            return [], "empty"
        conversations.clear()
        conversations.extend(new_list)
        return [_format_conv_summary(c) for c in new_list], "continue"

    idx, action = _interactive_picker(
        items,
        header="历史对话:",
        hint="提示: ↑↓ 选择  Enter 确认  d 删除",
        on_delete=on_delete,
    )

    if action != "selected" or idx is None:
        return False, config["current_model"]

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
        api_key=get_api_key(config),
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
                print_user_block(content, leading_newline=True)
            elif role == "assistant":
                print(f"\nAI: {strip_markdown_bold(content)}")
        print()
    return True, history_model


def _extract_contents_text(contents):
    """从 Grok 导出的 contents 字段拼出纯文本。"""
    if contents is None:
        return ""
    if isinstance(contents, str):
        return contents
    if not isinstance(contents, list):
        return str(contents)

    parts = []
    for item in contents:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        # 只取文本块；其它 type（图片、附件等）忽略
        if item.get("type", "text") == "text":
            text = item.get("content")
            if text is None:
                text = item.get("text", "")
            if text:
                parts.append(str(text))
    return "\n".join(parts)


def _normalize_import_role(role):
    if not role:
        return None
    role = str(role).strip().lower()
    if role in ("user", "human"):
        return "user"
    if role in ("assistant", "ai", "model", "bot", "grok"):
        return "assistant"
    return None


def parse_import_json(data):
    """
    从网页端导出的 JSON 中提取必要上下文。
    支持：
      - 消息数组（Grok 爬取格式：role + contents[].content）
      - 简单格式：role + content
      - 包装对象：{"messages": [...]}
    返回 [{role: user|assistant, content: str}, ...]
    格式不符时抛出 ValueError。
    """
    if data is None:
        raise ValueError("JSON 内容为空（null），需要消息数组或含 messages 的对象")

    if isinstance(data, dict):
        if isinstance(data.get("messages"), list):
            data = data["messages"]
        elif isinstance(data.get("data"), list):
            data = data["data"]
        else:
            raise ValueError(
                "JSON 对象格式不符合会话结构"
                "（需要 messages/data 数组，或根节点直接为消息数组）"
            )

    if not isinstance(data, list):
        raise ValueError(
            f"JSON 根节点类型无效: {type(data).__name__}，"
            "应为消息数组 [{role, content}, ...]"
        )

    if len(data) == 0:
        raise ValueError("消息数组为空，没有可导入的内容")

    result = []
    skipped = 0
    for item in data:
        if not isinstance(item, dict):
            skipped += 1
            continue
        role = _normalize_import_role(item.get("role"))
        if role is None:
            skipped += 1
            continue

        try:
            if "content" in item and item["content"] is not None and not isinstance(
                item.get("contents"), list
            ):
                content = item["content"]
                if not isinstance(content, str):
                    # 兼容 content 也是 contents 风格列表的情况
                    content = _extract_contents_text(content)
            elif "contents" in item:
                content = _extract_contents_text(item.get("contents"))
            else:
                content = ""

            if not isinstance(content, str):
                content = str(content) if content is not None else ""
        except Exception as e:
            raise ValueError(f"解析某条消息的文本内容失败: {e}") from e

        content = content.strip()
        if not content:
            skipped += 1
            continue
        result.append({"role": role, "content": content})

    if not result:
        raise ValueError(
            "未解析到有效的 user/assistant 文本消息"
            f"（共 {len(data)} 条记录，跳过 {skipped} 条）。"
            "每条需含 role（user/assistant）以及 content 或 contents 文本"
        )

    return result


def import_conversation(path, config, state):
    """
    /import 命令：从外部 JSON 导入会话，落盘为独立历史，并切换为当前对话。
    导入后不再依赖源文件。成功返回 True，失败返回 False。
    路径缺失、非 JSON、格式不符等异常均就地提示，不抛出到主循环。
    """
    try:
        return _import_conversation_impl(path, config, state)
    except Exception as e:
        print(f"错误: 导入失败: {e}")
        return False


def _import_conversation_impl(path, config, state):
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    path = (path or "").strip().strip('"').strip("'")
    if not path:
        print("用法: /import <绝对路径>")
        print("示例: /import C:\\path\\to\\chat.json")
        return False

    if not os.path.isabs(path):
        print("错误: 请使用绝对路径，例如 /import C:\\path\\to\\chat.json")
        return False

    if os.path.isdir(path):
        print(f"错误: 路径是目录，请指定 .json 文件: {path}")
        return False

    if not os.path.exists(path):
        print(f"错误: 文件不存在: {path}")
        return False

    if not os.path.isfile(path):
        print(f"错误: 不是普通文件: {path}")
        return False

    # 扩展名提示（仍允许尝试解析，但明确要求 json）
    _, ext = os.path.splitext(path)
    if ext.lower() != ".json":
        print(f"错误: 请导入 .json 文件（当前扩展名: {ext or '无'}）")
        return False

    try:
        size = os.path.getsize(path)
    except OSError as e:
        print(f"错误: 无法访问文件: {e}")
        return False

    if size == 0:
        print("错误: 文件为空，不是有效的会话 JSON")
        return False

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except UnicodeDecodeError:
        print("错误: 文件不是合法的 UTF-8 文本，无法作为 JSON 导入")
        return False
    except OSError as e:
        print(f"错误: 无法读取文件: {e}")
        return False

    if not raw.strip():
        print("错误: 文件内容为空，不是有效的会话 JSON")
        return False

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(
            f"错误: 不是合法 JSON"
            f"（第 {e.lineno} 行第 {e.colno} 列: {e.msg}）"
        )
        return False

    try:
        imported = parse_import_json(data)
    except ValueError as e:
        print(f"错误: JSON 格式不符合会话结构: {e}")
        return False

    # 切换前持久化当前非空会话
    current_conv = state.get("current_conv")
    if current_conv and current_conv.get("messages"):
        save_conversation(current_conv)

    model = state.get("current_model") or config.get("current_model", "")
    system_prompt = state.get("system_prompt", "")
    conv = new_conversation(model, system_prompt)
    conv["messages"] = imported
    save_conversation(conv)

    messages = [SystemMessage(content=system_prompt)]
    for m in imported:
        role = m.get("role")
        content = m.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))

    state["messages"] = messages
    state["current_conv"] = conv

    reset_screen_visual()
    print(
        f"已导入会话 [{conv['id']}]，消息数: {len(imported)}，"
        f"模型: {model}（已写入历史，不再依赖源文件）"
    )
    print("\n--- 导入的对话内容 ---")
    for m in imported:
        role = m.get("role")
        content = m.get("content", "")
        if role == "user":
            print_user_block(content, leading_newline=True)
        elif role == "assistant":
            print(f"\nAI: {strip_markdown_bold(content)}")
    print()
    return True


def export_conversation(path, state):
    """
    /export 命令：选择一条历史会话，导出为可被 /import 再次导入的 JSON。
    格式为 [{role, content}, ...]，只含上下文必要字段。
    路径缺失、目录不存在、权限/写入失败等均就地提示，不抛出到主循环。
    成功返回 True，失败或取消返回 False。
    """
    try:
        return _export_conversation_impl(path, state)
    except Exception as e:
        print(f"错误: 导出失败: {e}")
        return False


def _prepare_export_destination(path, conv_id):
    """
    解析导出目标路径：支持文件路径或目录。
    父目录不存在时尝试创建。成功返回最终文件绝对路径，失败返回 None。
    """
    looks_like_dir = (
        path.endswith(os.sep)
        or path.endswith("/")
        or path.endswith("\\")
    )

    if looks_like_dir or os.path.isdir(path):
        parent = path.rstrip("\\/") if looks_like_dir else path
        if os.path.exists(parent) and not os.path.isdir(parent):
            print(f"错误: 路径不是目录: {parent}")
            return None
        if not os.path.isdir(parent):
            try:
                os.makedirs(parent, exist_ok=True)
            except PermissionError:
                print(f"错误: 无权限创建目录: {parent}")
                return None
            except OSError as e:
                print(f"错误: 无法创建目录 {parent}: {e}")
                return None
        if not os.path.isdir(parent):
            print(f"错误: 目录不存在且无法创建: {parent}")
            return None
        final_path = os.path.join(parent, f"{conv_id}.json")
    else:
        _, ext = os.path.splitext(path)
        if ext.lower() != ".json":
            print(f"错误: 请导出为 .json 文件（当前扩展名: {ext or '无'}）")
            return None

        parent = os.path.dirname(path)
        if parent:
            if os.path.exists(parent) and not os.path.isdir(parent):
                print(f"错误: 父路径不是目录: {parent}")
                return None
            if not os.path.isdir(parent):
                try:
                    os.makedirs(parent, exist_ok=True)
                except PermissionError:
                    print(f"错误: 无权限创建目录: {parent}")
                    return None
                except OSError as e:
                    print(f"错误: 目录不存在且无法创建 {parent}: {e}")
                    return None
                if not os.path.isdir(parent):
                    print(f"错误: 目录不存在且无法创建: {parent}")
                    return None

        if os.path.exists(path) and os.path.isdir(path):
            print(f"错误: 目标路径是目录，请指定文件名或在路径末尾加分隔符: {path}")
            return None

        final_path = path

    # 目标若已存在，必须是可覆盖的普通文件
    if os.path.exists(final_path):
        if not os.path.isfile(final_path):
            print(f"错误: 目标已存在且不是普通文件: {final_path}")
            return None
        if not os.access(final_path, os.W_OK):
            print(f"错误: 目标文件不可写: {final_path}")
            return None
    else:
        check_dir = os.path.dirname(final_path) or "."
        if not os.access(check_dir, os.W_OK):
            print(f"错误: 目录不可写: {check_dir}")
            return None

    return final_path


def _export_conversation_impl(path, state):
    path = (path or "").strip().strip('"').strip("'")
    if not path:
        print("用法: /export <绝对路径>")
        print("示例: /export C:\\path\\to\\chat.json")
        return False

    if not os.path.isabs(path):
        print("错误: 请使用绝对路径，例如 /export C:\\path\\to\\chat.json")
        return False

    # 文件目标时先做扩展名校验，避免选完会话才发现路径非法
    looks_like_dir = (
        path.endswith(os.sep)
        or path.endswith("/")
        or path.endswith("\\")
        or os.path.isdir(path)
    )
    if not looks_like_dir:
        _, ext = os.path.splitext(path)
        if ext.lower() != ".json":
            print(f"错误: 请导出为 .json 文件（当前扩展名: {ext or '无'}）")
            return False
        parent = os.path.dirname(path)
        if parent and os.path.exists(parent) and not os.path.isdir(parent):
            print(f"错误: 父路径不是目录: {parent}")
            return False

    # 先落盘当前非空会话，使其出现在可选列表中
    current_conv = state.get("current_conv")
    if current_conv and current_conv.get("messages"):
        try:
            save_conversation(current_conv)
        except OSError as e:
            print(f"错误: 无法保存当前会话到缓存: {e}")
            return False
        except Exception as e:
            print(f"错误: 保存当前会话失败: {e}")
            return False

    try:
        conversations = list_conversations()
    except Exception as e:
        print(f"错误: 读取历史对话列表失败: {e}")
        return False

    if not conversations:
        print("暂无历史对话。")
        return False

    items = [_format_conv_summary(c) for c in conversations]
    try:
        idx, action = _interactive_picker(
            items,
            header="选择要导出的对话:",
            hint="提示: ↑↓ 选择  Enter 确认",
        )
    except Exception as e:
        print(f"错误: 选择列表失败: {e}")
        return False

    if action != "selected" or idx is None:
        print("已取消导出。")
        return False

    if idx < 0 or idx >= len(conversations):
        print("错误: 无效的选择。")
        return False

    chosen = conversations[idx]
    conv_id = chosen.get("id")
    if not conv_id:
        print("错误: 会话缺少 id，无法导出。")
        return False

    export_data = []
    try:
        for m in chosen.get("messages") or []:
            if not isinstance(m, dict):
                continue
            role = m.get("role")
            content = m.get("content", "")
            if role not in ("user", "assistant"):
                continue
            if content is None:
                content = ""
            if not isinstance(content, str):
                content = str(content)
            export_data.append({"role": role, "content": content})
    except Exception as e:
        print(f"错误: 整理导出会话内容失败: {e}")
        return False

    if not export_data:
        print("错误: 该会话没有可导出的消息。")
        return False

    final_path = _prepare_export_destination(path, conv_id)
    if not final_path:
        return False

    try:
        with open(final_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
    except PermissionError:
        print(f"错误: 无权限写入文件: {final_path}")
        return False
    except OSError as e:
        print(f"错误: 无法写入文件 {final_path}: {e}")
        return False
    except (TypeError, ValueError) as e:
        print(f"错误: JSON 序列化失败: {e}")
        return False

    if not os.path.isfile(final_path):
        print(f"错误: 写入后未找到导出文件: {final_path}")
        return False

    print(f"已导出会话 [{conv_id}]，{len(export_data)} 条消息 -> {final_path}")
    return True


def rewind_conversation(config, llm_ref, state):
    """
    /rewind 命令：回退到某一条用户消息之前（不删除该消息本身）。
    列表只展示用户发送过的消息。选中后：
      - state["messages"] 截断到该用户消息之前（不含它）
      - state["current_conv"]["messages"] 同步截断
      - 持久化到磁盘
      - 返回该用户消息原文，让主循环填入对话框
    取消或无可回退消息时返回 None。
    """
    from langchain_core.messages import AIMessage, HumanMessage

    messages = state.get("messages", [])
    if len(messages) <= 1:
        print("没有可回退的用户消息。")
        return None

    user_entries = []
    for i, msg in enumerate(messages):
        if isinstance(msg, HumanMessage):
            user_entries.append((i, msg.content))

    if not user_entries:
        print("没有用户消息可回退。")
        return None

    items = []
    for seq, (_, content) in enumerate(user_entries, 1):
        preview = strip_markdown_bold((content or "").strip().replace("\n", " "))
        if len(preview) > 60:
            preview = preview[:60] + "…"
        items.append(f"#{seq}  {preview}")

    idx, action = _interactive_picker(
        items,
        header="用户消息列表（选择要回退到哪一条之前）:",
        hint="提示: ↑ 回到更早的消息  Enter 确认",
        start_index=len(items) - 1,
    )

    if action != "selected" or idx is None:
        print("已取消。")
        return None

    selected_msg_index, selected_content = user_entries[idx]

    state["messages"] = messages[:selected_msg_index]

    new_conv_msgs = []
    for m in state["messages"][1:]:
        if isinstance(m, HumanMessage):
            new_conv_msgs.append({"role": "user", "content": m.content})
        elif isinstance(m, AIMessage):
            new_conv_msgs.append({"role": "assistant", "content": m.content})
    state["current_conv"]["messages"] = new_conv_msgs

    save_conversation(state["current_conv"])

    reset_screen_visual()
    print(
        f"已回退到 #{idx + 1} 消息之前，"
        f"共删除 {len(user_entries) - idx} 条用户消息及其后续 AI 回复。"
    )
    if new_conv_msgs:
        print("\n--- 当前对话内容 ---")
        for m in new_conv_msgs:
            role = m.get("role")
            content = m.get("content", "")
            if role == "user":
                print_user_block(content, leading_newline=True)
            elif role == "assistant":
                print(f"\nAI: {strip_markdown_bold(content)}")
        print()
    return selected_content
