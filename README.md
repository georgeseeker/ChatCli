# ChatCli

一个在电脑**命令行 / 控制台**里使用的 AI 聊天工具。

## 这个项目是干什么的？

ChatCli 主要配合 **谷歌浏览器（Chrome）的 AI Exporter 插件** 使用：

1. 你在网页里（例如 Grok 等）和 AI 聊过一段话  
2. 用 **AI Exporter** 把对话导出成 JSON 文件  
3. 在 ChatCli 里用 `/import` 把这个文件导入  
4. 之后就可以在**本地控制台**里接着聊，上下文还在  

也就是说：**网页里聊过的内容，可以接到本地继续聊。**

> **重要：** 本工具**不会**替你提供模型服务。你需要自己准备可用的 **API Key**（以及对应接口地址），写在配置文件里。没有 Key 就无法正常对话。

除了导入网页对话，你也可以把 ChatCli 当成普通的本地多模型聊天客户端来用。

---

## 你需要准备什么？

| 需要 | 说明 |
|------|------|
| 电脑 | Windows / Linux / macOS 均可 |
| Python | **3.10 或更高**（不会装的话先装 [Python 官网](https://www.python.org/downloads/)，安装时勾选 “Add Python to PATH”） |
| 网络 | 能访问你所用的 API（如 DeepSeek 等） |
| API Key | 向模型服务商申请，自己保管 |
| （可选）Chrome + AI Exporter | 若要从网页导出对话再导入 |

其它 Python 包**不用**事先一个个装：后面用 `pip install` 时会**自动下载全部依赖**。

---

## 小白启动教程（按顺序做）

### 第 1 步：下载项目

打开终端（Windows 可用 PowerShell 或「命令提示符」），执行：

```bash
git clone https://github.com/georgeseeker/ChatCli.git
cd ChatCli
```

没有 git 也可以：在 GitHub 页面点 **Code → Download ZIP**，解压后，用终端进入解压后的文件夹。

### 第 2 步：安装到 Python 环境

在项目文件夹里执行：

```bash
pip install -e .
```

这一步会：

- 安装 ChatCli  
- **自动安装**运行所需的全部依赖  
- 在系统里注册命令：`chatcli`  

如果提示 `pip` 不是命令，可试：

```bash
python -m pip install -e .
```

### 第 3 步：写配置文件（必须，且要填 API Key）

配置放在**你的用户目录**下，不在项目文件夹里：

| 系统 | 配置文件路径 |
|------|----------------|
| Windows | `C:\Users\你的用户名\.chatcli\config.json` |
| Linux / macOS | `~/.chatcli/config.json` |

**Windows（PowerShell）创建目录并打开编辑：**

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.chatcli" | Out-Null
notepad "$env:USERPROFILE\.chatcli\config.json"
```

**Linux / macOS：**

```bash
mkdir -p ~/.chatcli
nano ~/.chatcli/config.json
```

把下面内容粘进去，并改成**你自己的** Key 和模型（示例用 DeepSeek，可按服务商修改）：

```json
{
  "api_key": "DEEPSEEK_API_KEY",
  "models": {
    "deepseek-chat": {
      "base_url": "https://api.deepseek.com",
      "model": "deepseek-v4-flash",
      "system_prompt": "你是一个简洁、准确、有帮助的 AI 助手。"
    }
  },
  "current_model": "deepseek-v4-flash",
  "temperature": 0.7,
  "stream": true
}
```

#### `api_key` 怎么填？

两种方式，**二选一**：

**方式 A（推荐）：写环境变量的名字**

```json
"api_key": "DEEPSEEK_API_KEY"
```

然后在系统里设置这个环境变量为真正的密钥。

Windows PowerShell（当前窗口临时生效）：

```powershell
$env:DEEPSEEK_API_KEY = "sk-你的密钥"
```

Linux / macOS：

```bash
export DEEPSEEK_API_KEY="sk-你的密钥"
```

**方式 B：直接把密钥写进配置**

```json
"api_key": "sk-你的密钥"
```

更简单，但不要把含密钥的文件发给别人或传到公开网盘。

保存文件后进入下一步。

### 第 4 步：启动

在任意目录打开终端，输入：

```bash
chatcli
```

在**当前**终端里启动（cmd、PowerShell、Linux/macOS 终端均可）。启动时会**清空本窗口已有内容**，从顶部开始显示聊天界面。

看到类似「已启动」「输入 /help」就说明成功了。

也可以用：

```bash
python -m chatcli
```

### 第 5 步（重点）：从网页导入对话继续聊

1. 用 Chrome 打开你聊过天的网页  
2. 用 **AI Exporter** 插件导出对话，得到一个 **`.json` 文件**  
3. 记住这个文件的**完整路径**（绝对路径），例如：  
   - Windows：`C:\Users\张三\Downloads\chat.json`  
   - macOS：`/Users/zhangsan/Downloads/chat.json`  
4. 在 ChatCli 里输入（路径换成你的）：  

```text
/import C:\Users\张三\Downloads\chat.json
```

5. 导入成功后，历史消息会显示出来，你直接输入新问题即可**接着聊**  
6. 导入后的会话会保存在本机 `~/.chatcli/.cache/`，**不再依赖**那个导出文件  

导出到本地备份可用：

```text
/export C:\Users\张三\Desktop\backup.json
```

---

## 常用命令（聊天窗口里输入）

| 命令 | 作用 |
|------|------|
| `/help` | 查看完整帮助 |
| `/clear` | 清空当前对话，开新会话 |
| `/config` | 看当前配置和数据目录 |
| `/model` | 切换模型 |
| `/resume` | 从历史记录里恢复以前的会话 |
| `/import 绝对路径` | 导入 JSON（配合 AI Exporter） |
| `/export 绝对路径` | 把某条历史导出成 JSON |
| `/rewind` | 回退到某条用户消息，可改写重发 |
| `/exit` | 退出 |

### 输入框快捷键

| 按键 | 作用 |
|------|------|
| `Enter` | 发送 |
| `Shift+Enter` | 换行 |
| `↑` / `↓` | 多行时移动光标 |

---

## 数据存在哪里？

| 内容 | 位置 |
|------|------|
| 配置 | `~/.chatcli/config.json` |
| 聊天历史 | `~/.chatcli/.cache/` |

Windows 下的 `~` 就是 `C:\Users\你的用户名`。

这些文件在你自己电脑上，**不会**自动上传到 GitHub。

---

## 常见问题

**Q：提示找不到 `chatcli` 命令？**  
A：确认安装时用的是同一个 Python。试 `python -m pip install -e .`，再用 `python -m chatcli` 启动。

**Q：提示配置文件不存在？**  
A：按「第 3 步」建好 `~/.chatcli/config.json`。

**Q：提示 API 认证失败？**  
A：检查 `api_key` 是否填对、环境变量是否设置、Key 是否有效、是否有余额/权限。

**Q：导入失败？**  
A：路径必须是**绝对路径**，文件必须是 `.json`，且来自 AI Exporter / 本工具 `/export` 的对话格式。路径有空格时可用引号包起来。

**Q：`pip install -e .` 里的 `-e` 是什么？**  
A：可编辑安装，方便你改项目代码。只想用、不改代码，可以改成 `pip install .`，依赖同样会自动装全。

**Q：可以不装 AI Exporter 吗？**  
A：可以。没有插件也能直接当本地聊天客户端用；只是少了「从网页一键导出再导入」这条链路。

---

## 卸载

```bash
pip uninstall chatcli
```

配置和历史在 `~/.chatcli/`，若要一并删除，请手动删这个文件夹。

---

## 给想了解结构的人

```
ChatCli/
  pyproject.toml    # 打包与依赖，安装时自动装包
  main.py           # 可选：python main.py
  chatcli/          # 程序源码
    main.py         # 启动与聊天循环
    config.py       # 配置与用户目录
    cache.py        # 历史、导入导出
    ...

~/.chatcli/         # 你的配置和历史（本机）
  config.json
  .cache/
```
