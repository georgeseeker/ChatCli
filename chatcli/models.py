import sys

from chatcli.config import get_api_key, get_current_model_config, get_model_list, save_config
from chatcli.utils import READLINE_AVAILABLE

if sys.platform == "win32":
    import msvcrt


def switch_model(config, llm_ref):
    """
    切换模型
    llm_ref: 包含 llm 的可变引用，用于更新
    """
    from langchain_openai import ChatOpenAI

    current = config["current_model"]
    model_list = get_model_list(config)

    if not model_list:
        print("没有可用模型")
        return current

    print("\n可用模型:")

    def print_selection(idx):
        for i, cfg in enumerate(model_list):
            name = cfg.get("model")
            marker = ""
            if name == current:
                marker = " [当前]"
            prefix = "  >" if i == idx else "   "
            print(f"\033[K{prefix} {name}{marker}")
        print(f"\033[{len(model_list)}A", end="")

    if not READLINE_AVAILABLE:
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
        idx = 0
        print_selection(idx)

        while True:
            key = msvcrt.getch()

            if key == b'\xe0':
                key = msvcrt.getch()
                if key == b'H':
                    idx = (idx - 1) % len(model_list)
                    print_selection(idx)
                elif key == b'P':
                    idx = (idx + 1) % len(model_list)
                    print_selection(idx)
            elif key == b'\r' or key == b'\n':
                print()
                break
            elif key == b'\x03':
                print("\n已取消。")
                return current

    new_model = model_list[idx].get("model")
    if new_model == current:
        print("当前已是该模型。")
        return current

    config["current_model"] = new_model
    save_config(config)

    model_config = get_current_model_config(config)
    new_llm = ChatOpenAI(
        model=model_config["model"],
        api_key=get_api_key(config),
        base_url=model_config["base_url"],
        temperature=config.get("temperature", 0.7),
        streaming=config.get("stream", False)
    )
    llm_ref["llm"] = new_llm

    print(f"已切换到模型: {new_model}")
    return new_model