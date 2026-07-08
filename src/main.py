import json
import os
import subprocess
import sys


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


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

    # 校验 models 和 current_model
    if "models" not in config or not config["models"]:
        print("错误: config.json 中未配置 models 字段")
        exit(1)

    current = config.get("current_model")
    if not current or current not in config["models"]:
        print("错误: config.json 中 current_model 未指定或指定模型不存在")
        exit(1)

    return config


def save_config(config):
    """保存配置到文件"""
    config_path = os.path.join(BASE_DIR, "config.json")
    # 不保存 api_key 到文件
    config_to_save = {k: v for k, v in config.items() if k != "api_key"}
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_to_save, f, indent=2, ensure_ascii=False)


def get_current_model_config(config):
    """获取当前模型的配置"""
    current = config["current_model"]
    model_config = config["models"][current]
    return model_config


def print_help():
    """打印帮助信息"""
    print("""
可用命令:
  /help   - 显示此帮助信息
  /clear  - 清空上下文，保留 system prompt
  /config - 显示当前配置
  /model  - 切换模型
  /exit   - 退出聊天窗口
""")


def print_config(config):
    """打印当前配置"""
    current = config["current_model"]
    models = config["models"]

    print(f"""
当前模型: {current}
可用模型: {', '.join(models.keys())}

模型配置:
  temperature: {config.get("temperature", 0.7)}
  stream: {config.get("stream", False)}
  api_key_env: {config.get("api_key_env", "")}
""")


def print_models(config):
    """打印可用模型列表"""
    models = config["models"]
    current = config["current_model"]

    print("\n可用模型:")
    for i, name in enumerate(models.keys(), 1):
        marker = " [当前]" if name == current else ""
        print(f"  {i}. {name}{marker}")
    print()


def switch_model(config, llm_ref):
    """
    切换模型
    llm_ref: 包含 llm 的可变引用，用于更新
    """
    models = config["models"]
    current = config["current_model"]

    print_models(config)

    try:
        choice = input("选择模型编号 (直接回车取消): ").strip()
        if not choice:
            print("已取消。")
            return current

        idx = int(choice) - 1
        model_names = list(models.keys())
        if idx < 0 or idx >= len(model_names):
            print("无效的选择。")
            return current

        new_model = model_names[idx]
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

    except ValueError:
        print("请输入有效编号。")
        return current


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

    messages = [SystemMessage(content=system_prompt)]

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
                system_prompt = model_config.get("system_prompt", "")
                messages = [SystemMessage(content=system_prompt)]
                print("已清空上下文。")
                continue

            if user_input == "/config":
                print_config(config)
                continue

            if user_input == "/model":
                new_model = switch_model(config, llm_ref)
                if new_model != config["current_model"]:
                    continue
                # 如果模型切换了，需要清空上下文
                model_config = get_current_model_config(config)
                system_prompt = model_config.get("system_prompt", "")
                messages = [SystemMessage(content=system_prompt)]
                continue

            if user_input == "/exit":
                print("再见!")
                break

            messages.append(HumanMessage(content=user_input))

            if config.get("stream"):
                # 流式输出
                print("\nAI: ", end="", flush=True)
                response_content = ""
                for chunk in llm_ref["llm"].stream(messages):
                    if chunk.content:
                        content = strip_markdown_bold(chunk.content)
                        print(content, end="", flush=True)
                        response_content += content
                print()
                response = AIMessage(content=response_content)
            else:
                response = llm_ref["llm"].invoke(messages)
                content = strip_markdown_bold(response.content)
                print(f"\nAI: {content}")

            messages.append(response)
            messages = trim_history(messages, max_history_messages)

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
