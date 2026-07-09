import os
import subprocess
import sys

from cache import (
    new_conversation,
    reset_screen_visual,
    resume_conversation,
    rewind_conversation,
    save_conversation,
)
from config import (
    BASE_DIR,
    get_current_model_config,
    load_config,
    print_config,
    print_help,
)
from models import switch_model
from utils import StreamingBoldStripper, read_framed_input, strip_markdown_bold


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
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
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

            if user_input == "/rewind":
                prefill = rewind_conversation(config, llm_ref, state)
                if prefill is None:
                    continue
                print("[Rewind] 直接回车按原内容发送，或输入修改后的内容（/cancel 取消）:")
                edit = read_framed_input("You: ", initial=prefill or "").strip()
                if edit == "/cancel":
                    print("已取消。")
                    continue
                if not edit:
                    continue
                user_input = edit
                # 落入下方的常规消息处理流程

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