# Sonex

[English](README.md)

Sonex 是一个命令行音乐播放器，包含本地 React + Ink 终端界面，以及
FastAPI/WebSocket 后端。正常使用时只需要运行一个命令：`sonex` 会启动后端、
打开 TUI，并通过 WebSocket 同步聊天、设置提示、确认框和播放状态。

## 运行要求

运行 Sonex 安装脚本之前，请先安装这些系统运行时：

- Python 3.12，并且可以通过 `python3.12` 调用
- Node.js 和 `npm`
- Linux 或 WSL shell
- 可选：`vlc` 或 `mpv`，用于本地文件和 YouTube 播放

安装脚本会检查 Python、Node.js 和 npm，但不会替你安装系统软件包。

## 安装

在项目 checkout 目录中运行：

```bash
./scripts/install.sh
```

安装脚本会：

- 创建或复用 `.venv`
- 安装 Python 包和依赖
- 使用 `npm ci` 安装 React + Ink TUI 依赖
- 构建 `src/cli-ui/dist/index.js`
- 在 `~/.local/bin/sonex` 创建用户可直接运行的 `sonex` 启动器

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

## 启动 Sonex

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

## 给外部 Agent 使用的 MCP

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

## 检查安装状态

运行：

```bash
./scripts/doctor.sh
```

`doctor.sh` 会检查 Python 依赖、Node 依赖、TUI 构建产物、`sonex` 命令、
`~/.sonex`、可选本地播放器，以及 Spotify 配置状态。

## Provider 设置

Sonex 默认把本地凭据保存到 `~/.sonex`。如果想使用其他状态目录，可以设置
`SONEX_HOME`。

使用以下命令管理 LLM provider 凭据：

```bash
sonex auth login openai
sonex auth set-key openai
sonex auth list
sonex auth set-default openai
sonex auth logout openai
```

如果默认 provider 还没有配置好就开始聊天，TUI 会先进入交互式设置流程，不会
直接开始 planner 或 agent 工作。把 `ollama` 配置为默认 provider 时，可以作为
本地 provider 使用。

## 音乐服务设置

### Spotify

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

### Apple Music

Apple Music 需要 developer credentials 和 Music User Token：

```bash
sonex auth set-key apple_music --api-key '<json-or-path>'
sonex auth login apple_music --access-token <music-user-token>
```

Apple Music 播放需要 Sonex 的本地 MusicKit bridge。

### 本地和 YouTube 播放

如果需要播放本地文件或 YouTube，请安装 `vlc` 或 `mpv`。Spotify Connect 播放
不使用这些本地播放器。

## 故障排查

- `sonex: command not found`：确认 `~/.local/bin` 在 `PATH` 中，然后运行
  `./scripts/doctor.sh`。
- 找到了其他 `sonex` 命令：在当前 checkout 中运行
  `./scripts/install.sh --force-user-shim`。
- 运行时文件缺失：再次运行 `sonex`，bootstrap 启动器可以修复 `.venv`、TUI
  依赖和已构建的 TUI；也可以重新运行 `./scripts/install.sh`。
- TUI 提示 API 未运行：日常使用运行 `sonex`；调试时先运行 `sonex api`，再运行
  `sonex tui`。
- Spotify 无法播放：重新运行 `sonex auth login spotify`，检查 scope 和账号
  product，并确认 Spotify 已在某个设备上打开。
