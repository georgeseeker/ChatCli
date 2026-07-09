# ChatCli

Windows 控制台 LLM 聊天客户端。支持多模型切换、流式输出、历史会话、导入/导出，以及框线多行输入。

## 环境要求

- Windows
- Python 3.10+
- 依赖：

```bash
pip install langchain-core langchain-openai
```

## 快速开始

1. 在项目根目录创建 `config.json`（该文件已在 `.gitignore` 中，不会提交）：

```json
{
  "api_key": "DEEPSEEK_API_KEY",
  "models": {
    "deepseek-chat": {
      "base_url": "https://api.deepseek.com",
      "model": "deepseek-v4-flash",
      "system_prompt": "你是一个简洁、准确、有帮助的 AI 助手。"
    },
    "deepseek-v4": {
      "base_url": "https://api.deepseek.com",
      "model": "deepseek-v4-pro",
      "system_prompt": "你是一个更有深度的 AI 助手。"
    }
  },
  "current_model": "deepseek-v4-flash",
  "temperature": 0.7,
  "stream": true
}
```

2. 配置 `api_key`（见下一节）。

3. 启动：

```bash
python main.py
```

会打开新的控制台窗口进入聊天。

## 配置说明

| 字段 | 说明 |
|------|------|
| `api_key` | API 密钥配置，见下方说明 |
| `models` | 可用模型字典；每项含 `base_url`、`model`、`system_prompt` |
| `current_model` | 当前使用的模型名，须与某条 `models.*.model` 一致 |
| `temperature` | 采样温度 |
| `stream` | 是否流式输出 |
| `max_history_messages` | （可选）上下文消息条数上限；不设则不限制 |

### `api_key`

**可以写环境变量名字，也可以直接写密钥。**

解析规则：

1. 若存在与配置值同名的环境变量，则使用该环境变量的值；
2. 否则把配置值本身当作 API 密钥。

示例 — 使用环境变量（推荐）：

```json
"api_key": "DEEPSEEK_API_KEY"
```

PowerShell 设置：

```powershell
$env:DEEPSEEK_API_KEY = "sk-xxxxxxxx"
```

示例 — 直接写密钥：

```json
"api_key": "sk-xxxxxxxx"
```

> 注意：直接写密钥时请勿把 `config.json` 提交到公开仓库（项目已默认忽略该文件）。

## 命令

聊天中输入 `/help` 可查看完整说明。摘要如下：

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/clear` | 清空当前上下文，保留 system prompt，开新会话 |
| `/config` | 显示当前配置（直接密钥会脱敏） |
| `/model` | 切换模型（切换后开新会话） |
| `/resume` | 恢复历史会话（↑↓ 选择，Enter 确认，`d` 删除） |
| `/import <绝对路径>` | 从 JSON 导入会话并打开 |
| `/export <绝对路径>` | 选择历史会话，导出为可再导入的 JSON |
| `/rewind` | 回退到某条用户消息之前并预填重发 |
| `/exit` | 退出 |

### 输入框

| 按键 | 作用 |
|------|------|
| `Enter` | 发送 |
| `Shift+Enter` | 换行 |
| `↑` / `↓` | 在多行之间移动 |

### 导入 / 导出

- `/import C:\path\to\chat.json`  
  支持本工具导出的格式，以及从 Grok 网页端爬取的消息 JSON（只抽取 `role` 与文本内容）。导入后写入本地 `.cache/` 历史，可继续对话，不再依赖源文件。

- `/export C:\path\to\out.json`  
  弹出历史列表选择后导出为：

```json
[
  {"role": "user", "content": "..."},
  {"role": "assistant", "content": "..."}
]
```

该文件可再次 `/import`。

## 历史与缓存

会话保存在项目根目录的 `.cache/` 下（已 gitignore）。每条会话为独立 JSON，含模型、system prompt 与消息列表。

## 项目结构

```
ChatCli/
  main.py       # 入口与主循环
  config.py     # 配置加载与帮助
  models.py     # 模型切换
  cache.py      # 历史、resume/import/export/rewind
  utils.py      # 框线输入、流式 ** 剥离等
  config.json   # 本地配置（不入库）
  .cache/       # 会话缓存（不入库）
```

