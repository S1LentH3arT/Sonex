# 🎵 Sonex

[English](README.md)

Sonex 是一个命令行音乐播放器，包含本地 React + Ink 终端界面，以及
FastAPI/WebSocket 后端。正常使用时只需要运行一个命令：`sonex` 会启动后端、
打开 TUI，并通过 WebSocket 同步聊天、设置提示、确认框和播放状态。

## ✅ 运行要求

运行 Sonex 安装脚本之前，请先安装这些系统运行时：

- 🐍 Python 3.12，并且可以通过 `python3.12` 调用
- 🟢 Node.js 和 `npm`
- 🐧 Linux 或 WSL shell
- 🎬 可选：`vlc` 或 `mpv`，用于本地文件和 YouTube 播放

安装脚本会检查 Python、Node.js 和 npm，但不会替你安装系统软件包。

## 📦 安装

在项目 checkout 目录中运行：

```bash
./scripts/install.sh
```

安装脚本会：

- 🧱 创建或复用 `.venv`
- 🐍 安装 Python 包和依赖
- 🖥️ 使用 `npm ci` 安装 React + Ink TUI 依赖
- 🏗️ 构建 `src/cli-ui/dist/index.js`
- 🚀 在 `~/.local/bin/sonex` 创建用户可直接运行的 `sonex` 启动器

如果 `~/.local/bin` 不在你的 `PATH` 中，把它加入 shell 配置后重新打开 shell：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

安装脚本选项：

```bash
./scripts/install.sh --no-user-shim
./scripts/install.sh --force-user-shim
./scripts/install.sh --no-launch
```

使用 `--no-user-shim` 可以跳过创建 `~/.local/bin/sonex`。使用
`--force-user-shim` 可以把已有的 `sonex` shim 替换为当前 checkout 的启动器。
`--no-launch` 主要给 bootstrap 启动器使用，用于修复缺失的运行时组件。

## 🚀 启动 Sonex

运行应用：

```bash
sonex
```

这会同时启动 FastAPI 后端和 React + Ink TUI，是推荐的启动方式。

调试时可以把后端和 TUI 拆到两个终端中运行：

```bash
sonex api
sonex tui
```

如果只运行 `sonex tui` 而后端没有启动，TUI 会提示 Sonex API 未运行。日常使用
请优先运行 `sonex`。

也可以直接运行 virtualenv 内部命令：

```bash
.venv/bin/sonex
```

## 🤖 给外部 Agent 使用的 MCP

Sonex 提供本地 MCP server，Claude Code、Codex、Hermes Agent 以及其他 MCP
客户端都可以把 Sonex 当成音乐工具服务使用。默认只暴露只读工具，例如搜索、账号
状态、当前播放、最近播放和推荐。会改变真实播放状态的工具默认隐藏，除非你显式
开启。

正常运行 Sonex 时，FastAPI 后端也会在这里提供 MCP：

```text
http://127.0.0.1:9001/mcp
```

连接 Codex：

```bash
codex mcp add sonex --url http://127.0.0.1:9001/mcp
```

用 HTTP 连接 Claude Code：

```bash
claude mcp add --transport http sonex http://127.0.0.1:9001/mcp
```

让 Claude Code 以本地 stdio MCP server 方式启动 Sonex：

```bash
claude mcp add --transport stdio sonex -- sonex mcp
```

Hermes Agent 可以使用 HTTP：

```yaml
mcp_servers:
  sonex:
    url: "http://127.0.0.1:9001/mcp"
```

也可以使用 stdio：

```yaml
mcp_servers:
  sonex:
    command: "sonex"
    args: ["mcp"]
```

如果要单独调试 HTTP MCP server，可以运行：

```bash
sonex mcp --transport http --host 127.0.0.1 --port 9002
```

单独调试时的 URL 是 `http://127.0.0.1:9002/mcp`。

如果想把播放、暂停、切歌等会改变播放状态的工具暴露给可信任的本地 agent，可以
给 `sonex mcp` 加 `--allow-mutations`，或在启动 `sonex api` 之前设置
`SONEX_MCP_ALLOW_MUTATIONS=1`。

## 🩺 检查安装状态

运行：

```bash
./scripts/doctor.sh
```

`doctor.sh` 会检查 Python 依赖、Node 依赖、TUI 构建产物、`sonex` 命令、
`~/.sonex`、可选本地播放器，以及 Spotify 配置状态。

## 🔌 Provider 设置

Sonex 默认把本地凭据保存到 `~/.sonex`。如果想使用其他状态目录，可以设置
`SONEX_HOME`。

Sonex 现在优先为主流云端 LLM provider 调用官方 API：

- ✅ **OpenAI** 使用官方 chat completions 接口。
- ✅ **Anthropic** 使用官方 messages 接口。
- ✅ **Gemini** 使用官方 generate content 接口，并在配置 OAuth 时使用
  Authorization header。
- ✅ **DeepSeek** 保留 Sonex 已经在使用的官方 API adapter。
- 🚧 **LiteLLM** 仍作为自定义或暂未 native 化 provider 的兼容 fallback
  保留，但不再是以上云端 provider 的默认调用路径。

🔐 使用以下命令管理 LLM provider 凭据：

```bash
sonex auth login openai
sonex auth set-key openai
sonex auth list
sonex auth set-default openai
sonex auth logout openai
```

⚙️ 也可以使用环境变量配置：

```bash
export SONEX_DEFAULT_PROVIDER=openai
export SONEX_DEFAULT_MODEL=gpt-5.5
export SONEX_OPENAI_API_KEY=sk-...
export SONEX_ANTHROPIC_API_KEY=sk-ant-...
export SONEX_GEMINI_API_KEY=...
export SONEX_DEEPSEEK_API_KEY=sk-...
```

🧠 如果默认 provider 还没有配置好就开始聊天，TUI 会先进入交互式设置流程，不会
直接开始 planner 或 agent 工作。把 `ollama` 配置为默认 provider 时，可以作为
本地 provider 使用。

Sonex 会加载 `.env`，然后按以下顺序解析运行时配置：环境变量、`sonex auth`
保存的凭据，最后是 JSON 配置文件。设置 `SONEX_CONFIG_PATH` 可以使用
`~/.sonex/thinking.json` 之外的配置文件。

🛠️ 高级用户仍然可以在 `~/.sonex/thinking.json` 中按 provider 覆盖
`base_url`、`model`、`timeout`、`extra_headers` 和 `options`：

```json
{
  "default_provider": "openai",
  "default_model": "gpt-5.5",
  "providers": {
    "openai": {
      "base_url": "https://api.openai.com/v1",
      "model": "gpt-5.5",
      "timeout": 60,
      "extra_headers": {},
      "options": {}
    }
  },
  "beads": {
    "brand": "hama"
  }
}
```

## 🎧 音乐服务设置

### 🟩 Spotify

在 TUI 中输入：

```text
setup spotify
```

Sonex 会引导你创建 Spotify app、添加 loopback Redirect URI、输入 Client ID 和
Client Secret，并完成浏览器授权。

也可以从 CLI 启动 Spotify OAuth 流程：

```bash
sonex auth login spotify
```

Spotify app credentials 可以来自 `SPOTIFY_CLIENT_ID` 和
`SPOTIFY_CLIENT_SECRET`，也可以通过 TUI 引导设置保存。Spotify 播放控制需要
Spotify 账号和可用的 Spotify Connect 设备；播放控制需要 Premium。

设置完成后，可用 `/spotify` 进入持久化 Spotify 模式。进入前会检查已登录
Premium 账号、播放控制、playlist read scopes 和 `user-library-read` scope，以及
至少一个可用的 Spotify Connect 设备。成功进入后，Sonex 会在后续对话中恢复
Spotify mode，直到本地 Spotify token 过期、缺少必要 scopes，或你用 `/spotify` 或
`/spotify off` 退出。启动时的恢复只检查本地 token 和已保存设备信息，不调用 Spotify
账号或设备 API。模式开启后，播放/搜索、推荐、歌单和当前播放都会只使用 Spotify 工具。
在 Spotify 模式下，第一次执行 `/playlist` 会把已点赞歌曲导入为只读镜像
`[Spotify] Spotify Library`，并把 Spotify 歌单导入为只读本地镜像；本次 Spotify mode
后续 `/playlist` 只打开本地歌单浏览器，不再调用 Spotify API，直到退出后重新进入
Spotify mode。普通 Sonex 模式仍可浏览已导入的 Spotify 镜像，但 `/playlist save`
只会写入可编辑的 Sonex 歌单。`/queue` 会打开 Spotify 实时播放队列。如果 Spotify 返回
`429 Too Many Requests`，Sonex 会显示 Too Many Requests，并提示请求过于频繁、稍后重试。
如果已保存 token 缺少新增的 Spotify scopes，Sonex 会在当前聊天区启动 Spotify 授权引导，
帮助你授予更新后的权限。

### 🍎 Apple Music

Apple Music 需要 developer credentials 和 Music User Token：

```bash
sonex auth set-key apple_music --api-key '<json-or-path>'
sonex auth login apple_music --access-token <music-user-token>
```

Apple Music 播放需要 Sonex 的本地 MusicKit bridge。

### 📁 本地和 YouTube 播放

如果需要可控制的本地文件或在线播放，请安装 `mpv`。`auto` 为了播放稳定性只使用
`mpv`。`cvlc` 仍可在 `/player` 后端选择面板中作为显式诊断后端使用；Spotify
Connect 播放不使用这些本地播放器。

### 🌐 在线音频 fallback

当本地、Spotify 或 Apple Music 不可用时，Sonex 可以通过在线音频源解析选中的
歌曲。至少配置一个在线音频 provider：

```text
/setup jamendo
/setup audius
```

也可以通过环境变量提供凭据：

```bash
export SONEX_JAMENDO_CLIENT_ID=...
export SONEX_AUDIUS_API_KEY=...
```

解析器会把用户选中的歌曲身份和 provider 元数据分开保存，会重新校验缓存音频，并
在候选不可用时把 provider fallback 原因显示到 TUI 中。

## ▶️ 播放教程

使用自然语言播放请求：

```text
play Space Oddity David Bowie
play Mitski Nobody
播放 方大同 忘了美丽
```

Sonex 会展示最多五个曲目候选。选择曲目后，它会继续询问播放路径：优先本地、
Spotify、Apple Music，或在可用时使用在线音频。对于推荐类请求，Sonex 会先返回
编号文本列表；之后可以继续要求播放某一项，例如 `play number 2` 或 `播放第2首`。

本地或在线曲目播放时，可以使用：

```text
/pause
/resume
/stop
/progress
/volume 65
/player
```

`/player` 会打开后端选择面板。选择 `auto` 或 `mpv` 使用稳定的 mpv 路径；只有在
排查播放器相关问题时选择 `VLC`；取消则保持当前设置不变。

## 🧩 封面珠子图

TUI 可以把专辑封面渲染成静态实体拼豆图。Sonex 会优先使用官方封面，随后生成
`40x40`、`48x48`、`56x56`、`64x64`、`80x80`、`96x96` 这几档缓存方形变体。
当前算法使用共享、无抖动的 32 到 72 色调色板，并提高 80 和 96 预览尺寸的权重；
旧算法 profile 的缓存会自动失效并重新生成。

支持的拼豆目录是 5 mm Hama Midi、Perler Classic 和 Mard Standard Opaque。
Mard 的品牌/色号身份来自打包的官方品牌参考，RGB 近似值继续来自可再分发的社区
`beadcolors` 目录。可以在 `~/.sonex/thinking.json` 或 `SONEX_CONFIG_PATH`
指向的文件中配置品牌：

```json
{
  "beads": {
    "brand": "perler"
  }
}
```

如果省略 `beads.brand`，Sonex 使用 `hama`。生成的图案保存在
`~/.sonex/cache/cover_patterns`，该缓存不会保存原始封面图片字节。

## 🛟 故障排查

- 🧭 `sonex: command not found`：确认 `~/.local/bin` 在 `PATH` 中，然后运行
  `./scripts/doctor.sh`。
- 🔁 找到了其他 `sonex` 命令：在当前 checkout 中运行
  `./scripts/install.sh --force-user-shim`。
- 🧩 运行时文件缺失：再次运行 `sonex`，bootstrap 启动器可以修复 `.venv`、TUI
  依赖和已构建的 TUI；也可以重新运行 `./scripts/install.sh`。
- 🌐 TUI 提示 API 未运行：日常使用运行 `sonex`；调试时先运行 `sonex api`，再运行
  `sonex tui`。
- 🟩 Spotify 无法播放：scope 缺失时按 TUI 中的重授权引导操作，或重新运行
  `sonex auth login spotify`；检查账号 product，并确认 Spotify 已在某个设备上打开。
- 🎬 本地或在线播放无法启动：安装 `mpv`，打开 `/player`，保持 auto/mpv 后端；
  只有在手动测试 VLC 行为时选择 VLC。
- 🧩 封面珠子图没有出现：检查 `beads.brand`，用带官方封面的曲目重新播放，并查看
  `~/.sonex/log` 中的封面生成错误。
