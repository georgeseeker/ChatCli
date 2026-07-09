import json
import os


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_config():
    """加载并校验配置文件"""
    config_path = os.path.join(BASE_DIR, "config.json")

    if not os.path.exists(config_path):
        print(f"错误: 配置文件 {config_path} 不存在")
        exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

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

    if "models" not in config or not config["models"]:
        print("错误: config.json 中未配置 models 字段")
        exit(1)

    current = config.get("current_model")
    if not current:
        print("错误: config.json 中未配置 current_model 字段")
        exit(1)

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


def get_current_model_config(config):
    """获取当前模型的配置"""
    current = config["current_model"]
    for model_config in config["models"].values():
        if model_config.get("model") == current:
            return model_config
    return None


def get_model_list(config):
    """获取模型配置列表"""
    items = []
    for model_config in config["models"].values():
        if model_config.get("model"):
            items.append(model_config)
    return items


def print_help():
    """打印帮助信息"""
    print("""
可用命令:
  /help    - 显示此帮助信息
  /clear   - 清空上下文，保留 system prompt
  /config  - 显示当前配置
  /model   - 切换模型
  /resume  - 恢复历史对话（上下键选择，回车确认，按 d 删除）
  /import  - 从 JSON 导入会话（/import <绝对路径>），写入历史并打开
  /export  - 导出会话为 JSON（/export <绝对路径>），列表选择后写出可再导入格式
  /rewind  - 回退到某条用户消息之前并预填重发
  /exit    - 退出聊天窗口

输入框:
  Enter       - 发送
  Shift+Enter - 换行
  ↑/↓         - 在多行之间移动
""")


def print_config(config):
    """打印当前配置"""
    current = config["current_model"]
    models = config["models"]

    available = [m.get("model") for m in models.values()]

    print(f"""
当前模型: {current}
可用模型: {', '.join(available)}

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
    model_list = get_model_list(config)

    for i, cfg in enumerate(model_list, 1):
        name = cfg.get("model")
        marker = " [当前]" if name == current else ""
        print(f"  {i}. {name}{marker}")
    print()