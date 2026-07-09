import json
import os
import shutil
from pathlib import Path


# 项目源码目录（脚本所在位置，与用户数据目录分离）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 用户数据目录：跨平台家目录下的 .chatcli
# Windows: C:\Users\<用户>\.chatcli
# Linux/macOS: ~/.chatcli
CHATCLI_HOME: Path = Path.home() / ".chatcli"
CONFIG_PATH: Path = CHATCLI_HOME / "config.json"
CACHE_DIR: Path = CHATCLI_HOME / ".cache"


def ensure_chatcli_home():
    """确保 ~/.chatcli 与其中的 .cache 存在；必要时从旧项目目录迁移数据。"""
    CHATCLI_HOME.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    project_dir = Path(BASE_DIR)
    old_config = project_dir / "config.json"
    if not CONFIG_PATH.exists() and old_config.is_file():
        try:
            shutil.copy2(old_config, CONFIG_PATH)
        except OSError:
            pass

    old_cache = project_dir / ".cache"
    if old_cache.is_dir():
        try:
            for src in old_cache.glob("*.json"):
                dest = CACHE_DIR / src.name
                if not dest.exists():
                    shutil.copy2(src, dest)
        except OSError:
            pass


def _mask_secret(value):
    """脱敏展示密钥，避免 /config 泄露全文。"""
    if not value:
        return ""
    text = str(value)
    if len(text) <= 8:
        return "***"
    return f"{text[:3]}***{text[-3:]}"


def resolve_api_key(api_key_value):
    """
    解析 api_key：
      1. 若存在同名环境变量，取其值；
      2. 否则把配置值本身当作 API 密钥。
    返回 (resolved_key, source)，source 为 "env" 或 "direct"。
    """
    value = (api_key_value or "").strip() if isinstance(api_key_value, str) else ""
    if not value:
        return None, None
    env_val = os.environ.get(value)
    if env_val:
        return env_val, "env"
    return value, "direct"


def get_api_key(config):
    """返回已解析的 API 密钥（供 ChatOpenAI 等使用）。"""
    return config.get("_resolved_api_key")


def load_config():
    """加载并校验配置文件（位于用户目录 ~/.chatcli/config.json）"""
    ensure_chatcli_home()

    if not CONFIG_PATH.is_file():
        print(f"错误: 配置文件不存在: {CONFIG_PATH}")
        print(f"提示: 请在 {CHATCLI_HOME} 下创建 config.json")
        print(f"      Windows 示例: {Path.home() / '.chatcli' / 'config.json'}")
        exit(1)

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
    except OSError as e:
        print(f"错误: 无法读取配置文件 {CONFIG_PATH}: {e}")
        exit(1)
    except json.JSONDecodeError as e:
        print(f"错误: 配置文件不是合法 JSON: {CONFIG_PATH}")
        print(f"      第 {e.lineno} 行第 {e.colno} 列: {e.msg}")
        exit(1)

    raw_key = config.get("api_key")
    if isinstance(raw_key, str):
        raw_key = raw_key.strip()
    else:
        raw_key = ""

    if not raw_key:
        print(f"错误: {CONFIG_PATH} 中未配置 api_key 字段")
        print('提示: 可写环境变量名，如 "DEEPSEEK_API_KEY"')
        print('      或直接写密钥，如 "sk-xxxxxxxx"')
        exit(1)

    resolved, source = resolve_api_key(raw_key)
    if not resolved:
        print("错误: 无法解析 API 密钥")
        print('提示: api_key 可写环境变量名或直接写密钥')
        exit(1)

    # 落盘用原始配置值；请求用解析结果
    config["api_key"] = raw_key
    config["_resolved_api_key"] = resolved
    config["_api_key_source"] = source

    if "models" not in config or not config["models"]:
        print(f"错误: {CONFIG_PATH} 中未配置 models 字段")
        exit(1)

    current = config.get("current_model")
    if not current:
        print(f"错误: {CONFIG_PATH} 中未配置 current_model 字段")
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
    """保存配置到用户目录（不落盘运行时解析出的密钥与内部标记）"""
    ensure_chatcli_home()
    skip = {"_resolved_api_key", "_api_key_source"}
    config_to_save = {k: v for k, v in config.items() if k not in skip}
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config_to_save, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"错误: 无法写入配置文件 {CONFIG_PATH}: {e}")


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
可用命令
========

/help
  显示本帮助信息。

/clear
  清空当前对话上下文（用户与 AI 消息），保留当前模型的 system prompt，
  并开启一条新的历史会话。屏幕会清屏。

/config
  显示当前模型、可用模型列表，以及 temperature、stream、api_key 等配置。
  直接写在配置里的密钥会脱敏显示。配置文件位于用户目录 ~/.chatcli/config.json。

/model
  交互式切换模型（列表选择）。
  切换成功后会清空当前上下文，并用新模型的 system prompt 开新会话。

/resume
  从历史会话列表中恢复一条对话，继续聊。
  操作: ↑↓ 选择  Enter 确认  d 删除  Ctrl-C 取消
  恢复后会清屏并回放该会话内容；当前非空会话会先自动保存。

/import <绝对路径>
  从 JSON 文件导入会话，写入本地历史并立即打开，可无缝继续对话。
  示例: /import C:\\path\\to\\chat.json
  要求: 绝对路径、.json 文件；支持 Grok 导出或本工具 /export 的格式。
  导入后不再依赖源文件。路径缺失、非 JSON、格式不符会提示错误。

/export <绝对路径>
  将某条历史会话导出为可再 /import 的 JSON。
  示例: /export C:\\path\\to\\out.json
  输入后出现历史列表（↑↓ 选择  Enter 确认）；只导出 user/assistant 文本。
  路径可为 .json 文件，或已有/可创建的目录（目录下按会话 id 命名）。
  父目录不存在时会尝试创建；权限/路径错误会提示。

/rewind
  回退到某条用户消息之前（列表只显示用户消息）。
  选中后: 截断该条及之后的对话，并把该条内容预填进输入框以便改写重发。
  预填框内可: 直接回车发送、改写后发送、再输入 /rewind 继续回退、
  输入 /cancel 取消发送。

/exit
  退出聊天窗口。

输入框
======
  Enter       - 发送当前输入
  Shift+Enter - 换行（多行消息）
  ↑/↓         - 在多行之间移动光标
""")


def print_config(config):
    """打印当前配置"""
    current = config["current_model"]
    models = config["models"]

    available = [m.get("model") for m in models.values()]

    raw = config.get("api_key", "")
    source = config.get("_api_key_source")
    if source is None:
        _, source = resolve_api_key(raw)
    if source == "env":
        api_key_display = f"{raw} (环境变量)"
    elif source == "direct":
        api_key_display = f"{_mask_secret(raw)} (直接配置)"
    else:
        api_key_display = raw or "(未配置)"

    print(f"""
当前模型: {current}
可用模型: {', '.join(available)}

数据目录: {CHATCLI_HOME}
配置文件: {CONFIG_PATH}

模型配置:
  temperature: {config.get("temperature", 0.7)}
  stream: {config.get("stream", False)}
  api_key: {api_key_display}
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