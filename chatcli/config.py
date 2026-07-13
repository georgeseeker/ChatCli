import json
import os
import shutil
from pathlib import Path


# 包目录 / 仓库根（可编辑安装时仓库根在包的上一级）
PACKAGE_DIR = Path(__file__).resolve().parent
REPO_DIR = PACKAGE_DIR.parent
# 兼容旧名：部分逻辑仍引用 BASE_DIR 表示源码侧目录
BASE_DIR = str(REPO_DIR)

# 用户数据目录：跨平台家目录下的 .chatcli
# Windows: C:\Users\<用户>\.chatcli
# Linux/macOS: ~/.chatcli
CHATCLI_HOME: Path = Path.home() / ".chatcli"
CONFIG_PATH: Path = CHATCLI_HOME / "config.json"
CACHE_DIR: Path = CHATCLI_HOME / ".cache"

# 默认示例配置：用户删除 ~/.chatcli 或 config.json 时会按此重建
DEFAULT_CONFIG = {
    "api_key": "DEEPSEEK_API_KEY",
    "models": {
        "deepseek-chat": {
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-flash",
            "system_prompt": "你是一个简洁、准确、有帮助的 AI 助手。",
        },
        "deepseek-v4": {
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-pro",
            "system_prompt": "你是一个专业深入的 AI 助手。",
        },
    },
    "current_model": "deepseek-v4-flash",
    "temperature": 0.7,
    "stream": True,
    # /import grok 专用 Chrome user-data-dir；首次使用时会要求用户输入并落盘
    "cdp_user_data_dir": "",
    # /import grok 调试端口；首次使用时会要求用户输入（默认 9222）并落盘
    "cdp_port": 9222,
}


# /import grok 首次让用户输入 Chrome user-data-dir 时给的默认值（跨平台）
_DEFAULT_CDP_USER_DATA_DIR = str(Path.home() / "chrome-cdp-profile")
_DEFAULT_CDP_PORT = 9222


def write_default_config():
    """写入示例 config.json（两个 DeepSeek 模型样本）。"""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
            f.write("\n")
        return True
    except OSError as e:
        print(f"错误: 无法创建示例配置 {CONFIG_PATH}: {e}")
        return False


def ensure_chatcli_home():
    """
    确保 ~/.chatcli 与其中的 .cache 存在。
    若用户删除了整个目录或 config.json，会自动重建并写入示例配置。
    必要时从仓库根旧位置迁移数据。
    """
    try:
        CHATCLI_HOME.mkdir(parents=True, exist_ok=True)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"错误: 无法创建数据目录 {CHATCLI_HOME}: {e}")
        return

    # 仅当仓库根仍残留旧文件时迁移（site-packages 安装时通常无此路径）
    old_config = REPO_DIR / "config.json"
    if not CONFIG_PATH.exists() and old_config.is_file():
        try:
            shutil.copy2(old_config, CONFIG_PATH)
        except OSError:
            pass

    old_cache = REPO_DIR / ".cache"
    if old_cache.is_dir():
        try:
            for src in old_cache.glob("*.json"):
                dest = CACHE_DIR / src.name
                if not dest.exists():
                    shutil.copy2(src, dest)
        except OSError:
            pass

    # 仍无配置则写入内置示例（首次使用或用户删掉了 .chatcli / config.json）
    if not CONFIG_PATH.is_file():
        if write_default_config():
            print(f"已创建示例配置: {CONFIG_PATH}")
            print("请编辑 api_key（环境变量名或直接写密钥）后再开始对话。")


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
        # ensure 已尝试创建示例；仍失败则退出
        if not write_default_config():
            print(f"错误: 配置文件不存在且无法创建: {CONFIG_PATH}")
            exit(1)
        print(f"已创建示例配置: {CONFIG_PATH}")
        print("请编辑 api_key（环境变量名或直接写密钥）后再开始对话。")

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


def get_cdp_user_data_dir(config):
    """返回 config 里登记的 CDP Chrome user-data-dir；空字符串视为未配置（返回 None）。"""
    value = config.get("cdp_user_data_dir")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def get_cdp_port(config):
    """返回 config 里登记的 CDP 端口；缺省或非法时回退到 9222。"""
    raw = config.get("cdp_port", _DEFAULT_CDP_PORT)
    try:
        port = int(raw)
        if 1 <= port <= 65535:
            return port
    except (TypeError, ValueError):
        pass
    return _DEFAULT_CDP_PORT


def prompt_first_run_cdp_setup(config):
    """首次 /import grok 时让用户输入 Chrome profile 目录与端口，写回 config.json。

    跨平台默认：profile 在 ~/chrome-cdp-profile（用 Path.home() 拼），
    端口默认 9222。两项都直接回车采用默认值，输入新值则覆盖。
    已通过 config 校验过的字段不会被重新问（main.handle_import_grok
    应当在缺一不可时才调用本函数）。
    """
    ensure_chatcli_home()

    default_dir = _DEFAULT_CDP_USER_DATA_DIR  # 跨平台：~/chrome-cdp-profile
    default_port = _DEFAULT_CDP_PORT           # 9222

    print()
    print("首次使用 /import grok，需要指定两个参数：")
    print("  1) Chrome profile 目录：用来保存 grok.com 登录态，")
    print("     必须独立于日常 Chrome（避免和正在运行的 Chrome 抢同一份 profile）。")
    print(f"     默认 [{default_dir}]（跨平台 = ~/chrome-cdp-profile），直接回车采用。")
    print("  2) 调试端口：Chrome --remote-debugging-port 用，")
    print(f"     默认 [{default_port}]，直接回车采用。")
    print()

    # 1. profile 目录
    try:
        raw_dir = input(f"Chrome profile 目录 [{default_dir}]: ").strip()
    except EOFError:
        raw_dir = ""
    chosen_dir = raw_dir or default_dir
    chosen_dir = os.path.abspath(os.path.expanduser(chosen_dir))

    # 2. 端口
    try:
        raw_port = input(f"调试端口 [{default_port}]: ").strip()
    except EOFError:
        raw_port = ""
    chosen_port_raw = raw_port or str(default_port)
    try:
        chosen_port = int(chosen_port_raw)
        if not (1 <= chosen_port <= 65535):
            raise ValueError
    except ValueError:
        print(f"  端口非法，回退到默认 {default_port}")
        chosen_port = default_port

    config["cdp_user_data_dir"] = chosen_dir
    config["cdp_port"] = chosen_port
    save_config(config)
    print(f"已记录: cdp_user_data_dir = {chosen_dir}")
    print(f"已记录: cdp_port = {chosen_port}")
    print()


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
ChatCli 命令帮助
================
在输入框中输入下列命令（普通文字会当作发给 AI 的消息）。

----------------------------------------------------------------------
/help
  作用: 显示本帮助，列出全部命令的作用与用法。
  用法: /help

----------------------------------------------------------------------
/clear
  作用: 丢掉当前正在聊的上下文，重新开一场空对话。
  说明:
    - 用户消息与 AI 回复都会清空
    - 保留当前模型的 system prompt（人设）
    - 会清屏，并在本地历史里对应一条新会话
  用法: /clear

----------------------------------------------------------------------
/config
  作用: 查看当前运行配置，确认模型和密钥是否生效。
  说明:
    - 显示当前模型、可用模型、temperature、stream、api_key 等
    - 若密钥是直接写在配置里的，只会脱敏显示，不会完整打印
    - 同时显示数据目录与配置文件路径（~/.chatcli/）
  用法: /config

----------------------------------------------------------------------
/model
  作用: 切换到另一个已在 config.json 里配置好的模型。
  说明:
    - 用上下键选择，回车确认
    - 切换成功后会清空当前上下文，用新模型的 system prompt 开新会话
  用法: /model

----------------------------------------------------------------------
/resume
  作用: 从本机历史记录里挑一场旧对话，加载进来继续聊。
  说明:
    - 先自动保存当前非空会话，避免丢内容
    - 列表操作: ↑↓ 移动  Enter 确认  d 删除该条历史  Ctrl-C 取消
    - 确认后清屏并回放该会话的全部消息，之后可直接接着问
  用法: /resume

----------------------------------------------------------------------
/import <绝对路径>
  作用: 把外部 JSON 对话导入本地，并立刻打开，可无缝继续聊。
  典型场景: 用浏览器 AI Exporter 插件导出网页对话后，导入到本工具。
  说明:
    - 必须写文件的绝对路径，且扩展名为 .json
    - 支持 AI Exporter / Grok 网页导出，以及本工具 /export 的格式
    - 只抽取对话上下文（user / assistant 文本），其它无关字段忽略
    - 导入后写入 ~/.chatcli/.cache/，之后不再依赖原来的 JSON 文件
    - 路径不对、不是 JSON、格式不符时会提示错误，不会崩溃
  用法:
    /import C:\\Users\\你\\Downloads\\chat.json
    /import /home/你/Downloads/chat.json

----------------------------------------------------------------------
/import grok [url]
  作用: 直接从本地 Chrome 中已打开 / 指定的 grok.com 对话页抓取并导入，
        相当于把 Grok-Exporter 浏览器插件的功能做进 ChatCli。
  说明:
    - 无 url：抓当前已打开的 grok.com 对话页（URL 应形如 /c/<uuid>）
    - 带 url：让本地 Chrome 新开标签跳到该 URL，再抓
    - 抓取逻辑见 chatcli/fetchers/grok.{py,js}
    - 导入后写入 ~/.chatcli/.cache/，之后不再依赖源页面
  自动启动（不需要预先手动起 Chrome）:
    - CDP 未监听时，chatcli 会自动拉起一个后台 Chrome 进程。首次运行
      会一次性问你两个参数（回车即采用默认值），写入 ~/.chatcli/config.json：
        * Chrome profile 目录：默认 ~/chrome-cdp-profile（跨平台），
          必须独立于日常 Chrome
        * 调试端口：默认 9222
      写入后再次 /import grok 不再问，沿用已起的 Chrome 实例 + 配置
    - profile 必须独立于日常 Chrome（现代 Chrome 禁止两个进程共享
      同一份默认 profile）。首次需要在该 profile 下手动登录 grok.com
    - 已配置后想改值，直接编辑 ~/.chatcli/config.json 里的 cdp_user_data_dir
      或 cdp_port 字段即可
  备选：在 ~/.chatcli/config.json 里显式指定 Chrome 路径：
          "chrome_executable": "C:\\path\\to\\chrome.exe"
  用法:
    /import grok
    /import grok https://grok.com/c/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

----------------------------------------------------------------------
/export <绝对路径>
  作用: 把某条本机历史会话导出成 JSON，方便备份或再 /import。
  说明:
    - 先出现历史列表: ↑↓ 选择  Enter 确认
    - 只导出 user / assistant 的文本内容
    - 目标可以是 .json 文件路径；若写目录，则按会话 id 自动命名
    - 父目录不存在时会尝试创建；权限或路径错误会提示
  用法:
    /export C:\\Users\\你\\Desktop\\backup.json
    /export /home/你/Desktop/backup.json

----------------------------------------------------------------------
/rewind
  作用: 「时光倒流」到某条用户消息之前，方便改问题重问。
  说明:
    - 列表只显示你发过的用户消息（↑↓ 选择  Enter 确认）
    - 选中后: 删掉该条及其后面的对话，并把该条原文预填进输入框
    - 预填后可以: 直接回车重发 / 改写后再发 / 再输入 /rewind 继续往回退
    - 预填框里输入 /cancel 可取消本次发送（已回退的截断仍保留）
  用法: /rewind

----------------------------------------------------------------------
/exit
  作用: 退出聊天，关闭当前聊天窗口/结束进程。
  用法: /exit
  也可: Ctrl-C

----------------------------------------------------------------------
输入框快捷键
============
  Enter         发送当前输入
  Shift+Enter   换行（多行消息）
  ↑ / ↓         在多行之间移动光标

提示: 配置与历史在用户目录 ~/.chatcli/（Windows 为
      C:\\Users\\你的用户名\\.chatcli\\）。对话需要你自己提供 API Key。
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

CDP 配置（/import grok）:
  cdp_port: {config.get("cdp_port", 9222)}
  cdp_user_data_dir: {config.get("cdp_user_data_dir") or "(未配置，首次 /import grok 时会让你输入)"}
  chrome_executable: {config.get("chrome_executable") or "(自动探测)"}
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