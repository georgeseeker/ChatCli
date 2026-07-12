from chatcli.cache import _interactive_picker
from chatcli.config import (
    get_api_key,
    get_current_model_config,
    get_model_list,
    save_config,
)


def switch_model(config, llm_ref):
    """
    切换模型。
    复用 /resume 的 _interactive_picker：
      - Windows: ↑↓ 上下键 + Enter 确认，Ctrl-C 取消
      - 其它平台: 退化为编号输入
    llm_ref: 包含 llm 的可变引用，用于更新
    """
    from langchain_openai import ChatOpenAI

    current = config["current_model"]
    model_list = get_model_list(config)

    if not model_list:
        print("没有可用模型")
        return current

    items = []
    current_idx = 0
    for i, cfg in enumerate(model_list):
        name = cfg.get("model")
        marker = " [当前]" if name == current else ""
        items.append(f"{name}{marker}")
        if name == current:
            current_idx = i

    idx, action = _interactive_picker(
        items,
        header="可用模型:",
        hint="提示: ↑↓ 选择  Enter 确认  Esc/Ctrl-C 取消",
        start_index=current_idx,
    )

    if action != "selected" or idx is None:
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
        streaming=config.get("stream", False),
    )
    llm_ref["llm"] = new_llm

    print(f"已切换到模型: {new_model}")
    return new_model
